import hashlib
import json
import uuid
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import HTTPException, status
from sqlmodel import Session, select
from sqlalchemy import text
from sqlalchemy.orm import selectinload

from app.database import (
    get_or_create_month_archive,
    DiaryEntry,
    EntryContext,
    SampleAsset,
    IdempotencyKey,
    YearArchive,
    MonthArchive,
)
from app.storage import LocalStorageProvider
from app.pipeline import enqueue_processing

logger = logging.getLogger("sonochron.services.timeline")

# --- Storage singleton ---
storage = LocalStorageProvider(base_dir="backend/storage/raw")


async def create_diary_entry(
    session: Session,
    filename: str,
    content: bytes,
    local_capture_time: str,
    title: Optional[str] = None,
    mood: Optional[str] = None,
    location: Optional[str] = None,
    companions: Optional[str] = None,
    notes: Optional[str] = None,
    x_idempotency_key: Optional[str] = None,
) -> DiaryEntry:
    """
    Create a diary entry. Idempotency key prevents duplicate entries.
    Stores raw audio and enqueues background processing.
    """
    # 1. Parse local_capture_time
    try:
        capture_dt = datetime.fromisoformat(local_capture_time.replace("Z", "+00:00"))
    except Exception:
        capture_dt = datetime(2026, 6, 6, 12, 0, 0)

    # 2. Idempotency check
    if x_idempotency_key:
        existing_key = session.get(IdempotencyKey, x_idempotency_key)
        if existing_key:
            existing_entry = session.get(DiaryEntry, existing_key.entry_id)
            if existing_entry:
                return existing_entry

    # 3. Read file & compute checksum
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded file is empty.",
        )
    checksum = hashlib.sha256(content).hexdigest()
    byte_size = len(content)

    # 4. Parse companions
    companions_list: List[str] = []
    if companions:
        try:
            companions_list = json.loads(companions)
            if not isinstance(companions_list, list):
                companions_list = [companions]
        except (json.JSONDecodeError, ValueError):
            companions_list = [c.strip() for c in companions.split(",") if c.strip()]

    # 5. Build immutable storage key
    entry_id = uuid.uuid4()
    safe_filename = filename or f"recording_{entry_id}.bin"
    storage_key = f"{capture_dt.year}/{capture_dt.month:02d}/{entry_id}/{safe_filename}"

    # 6. Atomic Postgres transaction
    stored_path = None
    try:
        # 6a. Resolve/create YearArchive and MonthArchive
        month_archive = get_or_create_month_archive(session, capture_dt)

        # 6b. Create DiaryEntry
        entry = DiaryEntry(
            id=entry_id,
            local_capture_time=capture_dt,
            utc_capture_time=capture_dt,
            title=title,
            stage="uploaded",
            month_archive_id=month_archive.id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(entry)
        session.flush()

        # 6c. Create EntryContext
        context = EntryContext(
            entry_id=entry.id,
            mood=mood,
            location=location,
            companions=companions_list,
            notes=notes,
        )
        session.add(context)

        # 6d. Create SampleAsset
        asset = SampleAsset(
            entry_id=entry.id,
            filename=safe_filename,
            filepath=storage_key,
            checksum_sha256=checksum,
            byte_size=byte_size,
        )
        session.add(asset)

        # 6e. Register idempotency key
        if x_idempotency_key:
            idem = IdempotencyKey(
                key=x_idempotency_key,
                entry_id=entry.id,
                created_at=datetime.utcnow(),
            )
            session.add(idem)

        # 7. Persist raw audio inside the transaction block before commit
        stored_path = storage_key
        await storage.store_file(storage_key, content)

        session.commit()
    except Exception as exc:
        session.rollback()
        if stored_path:
            try:
                await storage.delete_file(stored_path)
            except Exception:
                pass
        raise exc

    # 8. Enqueue background processing
    await enqueue_processing(entry_id=entry.id)

    session.refresh(entry)
    return entry


def get_timeline_hierarchy(session: Session) -> List[Dict[str, Any]]:
    """Return the full year/month archive hierarchy."""
    years_stmt = select(YearArchive).order_by(YearArchive.year.desc())
    year_archives = session.exec(years_stmt).all()

    years_out = []
    for year_archive in year_archives:
        months_stmt = (
            select(MonthArchive)
            .where(MonthArchive.year == year_archive.year)
            .order_by(MonthArchive.month.desc())
        )
        month_archives = session.exec(months_stmt).all()

        months_out = []
        for ma in month_archives:
            entries_stmt = (
                select(DiaryEntry)
                .where(DiaryEntry.month_archive_id == ma.id)
                .order_by(DiaryEntry.local_capture_time.desc())
                .options(selectinload(DiaryEntry.context), selectinload(DiaryEntry.asset))
            )
            entries = session.exec(entries_stmt).all()
            entries_out = [entry_to_dict(entry) for entry in entries]
            entry_count = len(entries_out)
            months_out.append({
                "id": ma.id,
                "year": ma.year,
                "month": ma.month,
                "entry_count": entry_count,
                "entries": entries_out,
            })

        years_out.append({
            "year": year_archive.year,
            "months": months_out
        })

    return years_out


def list_diary_entries(
    session: Session,
    year: Optional[int] = None,
    month: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[DiaryEntry]:
    """List diary entries, optionally filtered by year and month."""
    stmt = select(DiaryEntry).order_by(DiaryEntry.local_capture_time.desc()).options(
        selectinload(DiaryEntry.context), selectinload(DiaryEntry.asset)
    )
    if year is not None or month is not None:
        stmt = stmt.join(MonthArchive, DiaryEntry.month_archive_id == MonthArchive.id)
        if year is not None:
            stmt = stmt.where(MonthArchive.year == year)
        if month is not None:
            stmt = stmt.where(MonthArchive.month == month)
    stmt = stmt.offset(offset).limit(limit)
    return session.exec(stmt).all()


def get_diary_entry(session: Session, entry_id: uuid.UUID) -> Optional[DiaryEntry]:
    """Get a single diary entry by ID."""
    return session.get(DiaryEntry, entry_id)


def get_diary_entry_asset(session: Session, entry_id: uuid.UUID) -> Optional[SampleAsset]:
    """Get sample asset for a diary entry."""
    return session.exec(
        select(SampleAsset).where(SampleAsset.entry_id == entry_id)
    ).first()


def update_diary_entry(
    session: Session,
    entry_id: uuid.UUID,
    patch_data: Dict[str, Any],
) -> DiaryEntry:
    """Partially update a diary entry's metadata and re-index in Qdrant."""
    entry = session.get(DiaryEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found.")

    context = session.exec(
        select(EntryContext).where(EntryContext.entry_id == entry_id)
    ).first()

    # Apply updates
    if "title" in patch_data and patch_data["title"] is not None:
        entry.title = patch_data["title"]
    entry.updated_at = datetime.utcnow()
    session.add(entry)

    if context:
        if "mood" in patch_data and patch_data["mood"] is not None:
            context.mood = patch_data["mood"]
        if "location" in patch_data and patch_data["location"] is not None:
            context.location = patch_data["location"]
        if "companions" in patch_data and patch_data["companions"] is not None:
            context.companions = patch_data["companions"]
        if "notes" in patch_data and patch_data["notes"] is not None:
            context.notes = patch_data["notes"]
        session.add(context)

    session.commit()
    session.refresh(entry)

    # Re-index updated entry in Qdrant (non-fatal)
    try:
        from app.search import upsert_entry, _build_entry_payload
        asset = session.exec(
            select(SampleAsset).where(SampleAsset.entry_id == entry_id)
        ).first()
        text_parts = []
        if entry.title:
            text_parts.append(entry.title)
        if context:
            if context.notes:     text_parts.append(context.notes)
            if context.mood:      text_parts.append(f"mood:{context.mood}")
            if context.location:  text_parts.append(f"location:{context.location}")
        text_content = " ".join(text_parts) or f"entry:{entry.id}"
        upsert_entry(
            entry_id=entry.id,
            text_content=text_content,
            audio_filepath=asset.filepath if asset else "",
            payload=_build_entry_payload(entry, context),
        )
    except Exception as exc:
        logger.warning("Qdrant re-index after patch failed: %s", exc)

    return entry


async def delete_diary_entry(session: Session, entry_id: uuid.UUID) -> None:
    """Permanently delete a diary entry and purge files."""
    entry = session.get(DiaryEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found.")

    # Get asset path before cascade delete
    asset = session.exec(
        select(SampleAsset).where(SampleAsset.entry_id == entry_id)
    ).first()
    storage_key = asset.filepath if asset else None

    # Remove from Qdrant (non-fatal)
    try:
        from app.search import delete_entry as qdrant_delete
        qdrant_delete(entry_id)
    except Exception as exc:
        logger.warning("Qdrant delete failed: %s", exc)

    # DB delete (cascades to context, asset, idempotency_keys)
    session.delete(entry)
    session.commit()

    # Purge audio file from storage (non-fatal)
    if storage_key:
        try:
            await storage.delete_file(storage_key)
        except Exception:
            pass  # Storage delete is best-effort


def reset_system(session: Session) -> None:
    """Delete all database rows, Qdrant collections, and clear files."""
    try:
        session.execute(text("DELETE FROM idempotency_keys;"))
        session.execute(text("DELETE FROM sample_assets;"))
        session.execute(text("DELETE FROM entry_contexts;"))
        session.execute(text("DELETE FROM diary_entries;"))
        session.execute(text("DELETE FROM month_archives;"))
        session.execute(text("DELETE FROM year_archives;"))
        session.commit()
    except Exception as e:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database reset failed: {str(e)}",
        )

    # Qdrant collections reset
    try:
        from app.search import TEXT_COLLECTION, AUDIO_COLLECTION, ensure_collections, _get_client
        client = _get_client()
        for coll in [TEXT_COLLECTION, AUDIO_COLLECTION]:
            try:
                client.delete_collection(coll)
            except Exception:
                pass
        ensure_collections()
    except Exception as e:
        logger.warning("Qdrant collections reset failed: %s", e)

    # Clear physical storage files
    try:
        import shutil
        if storage.base_dir.exists():
            for child in storage.base_dir.iterdir():
                try:
                    if child.is_file() or child.is_symlink():
                        child.unlink()
                    elif child.is_dir():
                        shutil.rmtree(child)
                except Exception:
                    pass
    except Exception as e:
        logger.warning("Physical storage cleanup failed: %s", e)


def entry_to_dict(entry: DiaryEntry) -> Dict[str, Any]:
    """Hydrate a DiaryEntry into a dictionary representing DiaryEntryOut."""
    context = entry.context
    asset = entry.asset

    context_out = None
    if context:
        context_out = {
            "mood": context.mood,
            "location": context.location,
            "companions": context.companions or [],
            "notes": context.notes,
        }

    asset_out = None
    if asset:
        asset_out = {
            "id": asset.id,
            "filename": asset.filename,
            "filepath": asset.filepath,
            "checksum_sha256": getattr(asset, "checksum_sha256", None),
            "duration_ms": getattr(asset, "duration_ms", None),
            "byte_size": getattr(asset, "byte_size", None),
        }

    return {
        "id": entry.id,
        "local_capture_time": entry.local_capture_time,
        "utc_capture_time": getattr(entry, "utc_capture_time", None),
        "title": getattr(entry, "title", None),
        "stage": entry.stage,
        "created_at": getattr(entry, "created_at", entry.local_capture_time),
        "updated_at": getattr(entry, "updated_at", entry.local_capture_time),
        "context": context_out,
        "asset": asset_out,
    }
