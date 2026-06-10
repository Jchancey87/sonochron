import logging

logger = logging.getLogger("sonochron.services.drive")

# --- Auto-sync state ---
_sync_state: dict = {
    "last_run":    None,   # ISO timestamp
    "last_count":  0,      # files imported in last sync
    "last_error":  None,   # error string if last sync failed
    "running":     False,
}


def get_sync_state() -> dict:
    """Return a copy of the auto-sync status."""
    return dict(_sync_state)


from app.drive import (
    is_authenticated,
    get_folder_id,
    get_auth_url,
    exchange_code,
    revoke as revoke_access,
    list_audio_files,
)


def get_drive_status() -> dict:
    """Get the current Drive authentication and sync status."""
    return {
        "authenticated": is_authenticated(),
        "folder_id": get_folder_id(),
        "sync": get_sync_state(),
    }


def list_drive_files():
    """List audio files from Google Drive."""
    from fastapi import HTTPException
    if not is_authenticated():
        raise HTTPException(status_code=401, detail="Not authenticated with Google Drive")
    try:
        return list_audio_files()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


async def import_drive_file(file_id: str, filename: str = "") -> str:
    """Import a single Drive file by downloading, converting and registering it."""
    import asyncio
    from fastapi import HTTPException
    from app.drive import get_imported_ids

    if not is_authenticated():
        raise HTTPException(status_code=401, detail="Not authenticated with Google Drive")

    # Resolve filename if not provided
    if not filename:
        try:
            files = list_audio_files()
            match = next((f for f in files if f["id"] == file_id), None)
            if match:
                filename = match["name"]
        except Exception:
            pass
    filename = filename or f"{file_id}.m4a"

    if file_id in get_imported_ids():
        raise HTTPException(status_code=409, detail="File already imported")

    try:
        loop = asyncio.get_event_loop()
        entry_id = await loop.run_in_executor(None, _import_file_sync, file_id, filename)
        return entry_id
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


async def trigger_sync() -> int:
    """Trigger a manual sync of all unimported Drive files."""
    from fastapi import HTTPException
    if not is_authenticated():
        raise HTTPException(status_code=401, detail="Not authenticated with Google Drive")
    return await run_auto_sync()


async def run_auto_sync() -> int:
    """
    Import all unimported audio files from Drive.
    Returns the number of new files imported.
    """
    from datetime import datetime, timezone
    import asyncio

    if _sync_state["running"]:
        logger.info("Auto-sync already running, skipping.")
        return 0

    _sync_state["running"] = True
    count = 0
    try:
        if not is_authenticated():
            _sync_state["last_error"] = "Not authenticated"
            return 0

        files = list_audio_files()
        new_files = [f for f in files if not f.get("already_imported")]
        logger.info("Auto-sync: %d new file(s) to import", len(new_files))

        for f in new_files:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, _import_file_sync, f["id"], f["name"]
                )
                count += 1
            except Exception as exc:
                logger.error("Auto-sync: failed to import %s: %s", f["name"], exc)

        _sync_state["last_run"]   = datetime.now(timezone.utc).isoformat()
        _sync_state["last_count"] = count
        _sync_state["last_error"] = None
        logger.info("Auto-sync complete: %d imported.", count)
    except Exception as exc:
        _sync_state["last_error"] = str(exc)
        logger.error("Auto-sync failed: %s", exc)
    finally:
        _sync_state["running"] = False

    return count


def _import_file_sync(drive_file_id: str, filename: str) -> str:
    """
    Synchronous import: download → convert → ingest through pipeline.
    Returns the new entry ID.
    """
    import uuid
    from datetime import datetime, timezone
    from pathlib import Path
    import hashlib
    import os
    import asyncio
    from sqlmodel import Session, select

    from app.database import engine, DiaryEntry, EntryContext, SampleAsset, MonthArchive, YearArchive, IdempotencyKey
    from app.pipeline import enqueue_processing
    from app.drive import download_and_convert, mark_imported, get_imported_ids
    from app.services.timeline_service import storage

    wav_path = download_and_convert(drive_file_id, filename)

    try:
        wav_file = Path(wav_path)
        byte_size = wav_file.stat().st_size
        checksum  = hashlib.sha256(wav_file.read_bytes()).hexdigest()

        # Derive a clean title from the filename (strip extension)
        title = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
        now   = datetime.now(timezone.utc)

        with Session(engine) as session:
            entry_id = uuid.uuid4()
            idempotency_key = f"drive:{drive_file_id}"

            # Check idempotency
            existing_key = session.get(IdempotencyKey, idempotency_key)
            if existing_key:
                logger.info("File %s already imported (idempotency key exists)", filename)
                mark_imported(drive_file_id, str(existing_key.entry_id))
                return str(existing_key.entry_id)

            # Ensure year/month archive
            year_val  = now.year
            month_val = now.month

            year_archive = session.get(YearArchive, year_val)
            if not year_archive:
                year_archive = YearArchive(year=year_val)
                session.add(year_archive)
                session.flush()

            month_archive = session.exec(
                select(MonthArchive).where(
                    MonthArchive.year == year_val,
                    MonthArchive.month == month_val,
                )
            ).first()
            if not month_archive:
                month_archive = MonthArchive(year=year_val, month=month_val)
                session.add(month_archive)
                session.flush()

            # Create entry
            entry = DiaryEntry(
                id=entry_id,
                month_archive_id=month_archive.id,
                local_capture_time=now,
                utc_capture_time=now,
                title=title,
                stage="uploaded",
            )
            session.add(entry)

            context = EntryContext(entry_id=entry_id)
            session.add(context)

            # Store WAV under the normal storage layout using StorageProvider
            dest_name = f"{Path(filename).stem}.wav"
            rel_path = f"{year_val}/{month_val:02d}/{entry_id}/{dest_name}"
            
            wav_bytes = Path(wav_path).read_bytes()
            
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(storage.store_file(rel_path, wav_bytes))
            finally:
                loop.close()

            asset = SampleAsset(
                entry_id=entry_id,
                filename=dest_name,
                filepath=rel_path,
                checksum_sha256=checksum,
                byte_size=byte_size,
            )
            session.add(asset)

            idem = IdempotencyKey(key=idempotency_key, entry_id=entry_id)
            session.add(idem)

            session.commit()

        mark_imported(drive_file_id, str(entry_id))
        logger.info("Drive file %s ingested as entry %s", filename, entry_id)

        # Kick off pipeline (transcribe → embed → index)
        asyncio.run(enqueue_processing(entry_id))

        return str(entry_id)
    finally:
        Path(wav_path).unlink(missing_ok=True)


def start_drive_sync_loop() -> None:
    """Start the Google Drive background sync task loop."""
    import asyncio
    import logging

    async def _drive_sync_loop():
        while True:
            await asyncio.sleep(30 * 60)  # wait 30 min between syncs
            if is_authenticated():
                try:
                    await run_auto_sync()
                except Exception as exc:
                    logging.getLogger("sonochron.drive").error(
                        "Auto-sync loop error: %s", exc
                    )

    asyncio.create_task(_drive_sync_loop())
