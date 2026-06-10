import hashlib
import json
import uuid
from datetime import datetime
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Header, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select
from sqlalchemy import text
from sqlalchemy.orm import selectinload

from app.database import (
    init_db,
    get_session,
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
from app.search import search_text, search_similar_audio, ensure_collections

# --- Storage singleton ---
storage = LocalStorageProvider(base_dir="backend/storage/raw")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB tables and Qdrant collections on startup."""
    import asyncio
    init_db()
    ensure_collections()

    # Start Drive auto-sync background loop (every 30 minutes)
    async def _drive_sync_loop():
        from app.drive import run_auto_sync, is_authenticated
        while True:
            await asyncio.sleep(30 * 60)  # wait 30 min between syncs
            if is_authenticated():
                try:
                    await run_auto_sync()
                except Exception as exc:
                    import logging
                    logging.getLogger("sonochron.drive").error(
                        "Auto-sync loop error: %s", exc
                    )

    asyncio.create_task(_drive_sync_loop())
    yield


app = FastAPI(
    title="Sonochron API",
    description="Personal sound diary — capture, archive, rediscover.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://192.168.0.204:5173",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://sonochron.homma.casa",
        "https://sonochron.homma.casa:5173",
        "http://sonochron.homma.casa",
        "http://sonochron.homma.casa:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------

class SampleAssetOut(BaseModel):
    id: uuid.UUID
    filename: str
    filepath: str
    checksum_sha256: Optional[str] = None
    duration_ms: Optional[int] = None
    byte_size: Optional[int] = None
    model_config = {"from_attributes": True}


class EntryContextOut(BaseModel):
    mood: Optional[str] = None
    location: Optional[str] = None
    companions: List[str] = []
    notes: Optional[str] = None
    model_config = {"from_attributes": True}


class DiaryEntryOut(BaseModel):
    id: uuid.UUID
    local_capture_time: datetime
    utc_capture_time: Optional[datetime] = None
    title: Optional[str] = None
    stage: str
    created_at: datetime
    updated_at: datetime
    context: Optional[EntryContextOut] = None
    asset: Optional[SampleAssetOut] = None
    model_config = {"from_attributes": True}


class MonthArchiveOut(BaseModel):
    id: uuid.UUID
    year: int
    month: int
    entry_count: int
    entries: List[DiaryEntryOut] = []
    model_config = {"from_attributes": True}


class YearArchiveOut(BaseModel):
    year: int
    months: List[MonthArchiveOut]
    model_config = {"from_attributes": True}


class TimelineOut(BaseModel):
    years: List[YearArchiveOut]


# ---------------------------------------------------------------------------
# Ingestion endpoint
# ---------------------------------------------------------------------------

@app.post(
    "/api/entries",
    response_model=DiaryEntryOut,
    status_code=status.HTTP_200_OK,
    summary="Ingest a new diary entry with optional audio upload",
)
async def create_entry(
    file: UploadFile = File(...),
    local_capture_time: str = Form(...),
    title: Optional[str] = Form(None),
    mood: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    companions: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    x_idempotency_key: Optional[str] = Header(None),
    session: Session = Depends(get_session),
):
    """
    Create a diary entry. Idempotency key in X-Idempotency-Key header prevents
    duplicate entries on retry. Stores raw audio immutably and enqueues processing.
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
                return _entry_to_out(existing_entry, session)

    # 3. Read file & compute checksum
    content = await file.read()
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
    safe_filename = file.filename or f"recording_{entry_id}.bin"
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
    return _entry_to_out(entry, session)


# ---------------------------------------------------------------------------
# Timeline endpoint
# ---------------------------------------------------------------------------

@app.get(
    "/api/timeline",
    response_model=List[YearArchiveOut],
    summary="Return the full year/month archive hierarchy",
)
def get_timeline(session: Session = Depends(get_session)):
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
            entries_out = [_entry_to_out(entry, session) for entry in entries]
            entry_count = len(entries_out)
            months_out.append(MonthArchiveOut(
                id=ma.id,
                year=ma.year,
                month=ma.month,
                entry_count=entry_count,
                entries=entries_out,
            ))

        years_out.append(YearArchiveOut(year=year_archive.year, months=months_out))

    return years_out


# ---------------------------------------------------------------------------
# Entry listing by month/year
# ---------------------------------------------------------------------------

@app.get(
    "/api/entries",
    response_model=List[DiaryEntryOut],
    summary="List diary entries, optionally filtered by year and month",
)
def list_entries(
    year: Optional[int] = None,
    month: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
):
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
    entries = session.exec(stmt).all()
    return [_entry_to_out(e, session) for e in entries]


# ---------------------------------------------------------------------------
# Single entry retrieval
# ---------------------------------------------------------------------------

@app.get(
    "/api/entries/{entry_id}",
    response_model=DiaryEntryOut,
    summary="Get a single diary entry by ID",
)
def get_entry(entry_id: uuid.UUID, session: Session = Depends(get_session)):
    entry = session.get(DiaryEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found.")
    return _entry_to_out(entry, session)


# ---------------------------------------------------------------------------
# Audio streaming
# ---------------------------------------------------------------------------

@app.get(
    "/api/entries/{entry_id}/audio",
    summary="Stream the raw audio for a diary entry",
)
async def get_audio(entry_id: uuid.UUID, session: Session = Depends(get_session)):
    entry = session.get(DiaryEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found.")

    asset = session.exec(
        select(SampleAsset).where(SampleAsset.entry_id == entry_id)
    ).first()
    if not asset:
        raise HTTPException(status_code=404, detail="No audio asset for this entry.")

    try:
        file_path = storage._get_safe_path(asset.filepath)
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError()
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="Audio file not found in storage.")

    fname = asset.filename.lower()
    if fname.endswith(".mp3"):
        media_type = "audio/mpeg"
    elif fname.endswith(".wav"):
        media_type = "audio/wav"
    elif fname.endswith(".ogg"):
        media_type = "audio/ogg"
    elif fname.endswith(".webm"):
        media_type = "audio/webm"
    else:
        media_type = "application/octet-stream"

    return FileResponse(path=str(file_path), media_type=media_type, filename=asset.filename)


# ---------------------------------------------------------------------------
# Waveform endpoint
# ---------------------------------------------------------------------------

class WaveformOut(BaseModel):
    entry_id: uuid.UUID
    peaks: List[float]  # num_bars values in [0, 1]
    num_bars: int


@app.get(
    "/api/entries/{entry_id}/waveform",
    response_model=WaveformOut,
    summary="Get real waveform peak data for a diary entry",
)
async def get_waveform(
    entry_id: uuid.UUID,
    bars: int = 100,
    session: Session = Depends(get_session),
):
    """
    Extract and return downsampled waveform peak amplitudes for UI display.
    Uses librosa RMS per-chunk on the actual audio file.
    `bars` controls the number of data points returned (default 100).
    """
    entry = session.get(DiaryEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found.")

    asset = session.exec(
        select(SampleAsset).where(SampleAsset.entry_id == entry_id)
    ).first()
    if not asset:
        raise HTTPException(status_code=404, detail="No audio asset for this entry.")

    try:
        from app.ml import extract_waveform_peaks
        import asyncio
        loop = asyncio.get_event_loop()
        async with storage.local_filepath(asset.filepath) as local_path:
            peaks = await loop.run_in_executor(
                None, lambda: extract_waveform_peaks(str(local_path), num_bars=bars)
            )
    except Exception as exc:
        import logging
        logging.getLogger("sonochron.api").warning("Waveform extraction failed: %s", exc)
        peaks = [0.0] * bars

    return WaveformOut(entry_id=entry_id, peaks=peaks, num_bars=len(peaks))


# ---------------------------------------------------------------------------
# Edit + Delete endpoints
# ---------------------------------------------------------------------------

class EntryPatch(BaseModel):
    title: Optional[str] = None
    mood: Optional[str] = None
    location: Optional[str] = None
    companions: Optional[List[str]] = None
    notes: Optional[str] = None


@app.patch(
    "/api/entries/{entry_id}",
    response_model=DiaryEntryOut,
    summary="Partially update a diary entry's metadata",
)
def patch_entry(
    entry_id: uuid.UUID,
    patch: EntryPatch,
    session: Session = Depends(get_session),
):
    """
    Partially update title, mood, location, companions, or notes.
    Only provided (non-null) fields are updated. Re-indexes the entry in Qdrant.
    """
    entry = session.get(DiaryEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found.")

    context = session.exec(
        select(EntryContext).where(EntryContext.entry_id == entry_id)
    ).first()

    # Apply updates
    if patch.title is not None:
        entry.title = patch.title
    entry.updated_at = datetime.utcnow()
    session.add(entry)

    if context:
        if patch.mood is not None:
            context.mood = patch.mood
        if patch.location is not None:
            context.location = patch.location
        if patch.companions is not None:
            context.companions = patch.companions
        if patch.notes is not None:
            context.notes = patch.notes
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
        import logging
        logging.getLogger("sonochron.api").warning("Qdrant re-index after patch failed: %s", exc)

    ctx = session.exec(select(EntryContext).where(EntryContext.entry_id == entry_id)).first()
    asset = session.exec(select(SampleAsset).where(SampleAsset.entry_id == entry_id)).first()
    return _entry_to_out(entry, session)


@app.delete(
    "/api/entries/{entry_id}",
    status_code=204,
    summary="Delete a diary entry and its audio file",
)
async def delete_entry(
    entry_id: uuid.UUID,
    session: Session = Depends(get_session),
):
    """
    Permanently delete a diary entry. Cascades to EntryContext, SampleAsset,
    and IdempotencyKey. Also purges the audio file from storage and removes
    the entry from the Qdrant index.
    """
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
        import logging
        logging.getLogger("sonochron.api").warning("Qdrant delete failed: %s", exc)

    # DB delete (cascades to context, asset, idempotency_keys)
    session.delete(entry)
    session.commit()

    # Purge audio file from storage (non-fatal)
    if storage_key:
        try:
            await storage.delete_file(storage_key)
        except Exception:
            pass  # Storage delete is best-effort


# ---------------------------------------------------------------------------
# Search endpoints
# ---------------------------------------------------------------------------

class SearchResultItem(BaseModel):
    id: uuid.UUID
    entry_id: uuid.UUID
    score: float
    title: Optional[str] = None
    mood: Optional[str] = None
    location: Optional[str] = None
    year: Optional[int] = None
    month: Optional[int] = None


@app.get(
    "/api/search",
    response_model=List[SearchResultItem],
    summary="Semantic text search over diary entries",
)
def search_entries(
    q: Optional[str] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
    mood: Optional[str] = None,
    limit: int = 10,
    similarity_entry_id: Optional[uuid.UUID] = None,
):
    """
    Search diary entries by semantic text similarity.
    Optionally filter results by year, month, or mood.
    """
    filters = {}
    if year is not None:
        filters["year"] = year
    if month is not None:
        filters["month"] = month
    if mood is not None:
        filters["mood"] = mood

    if similarity_entry_id is not None:
        results = search_similar_audio(
            reference_entry_id=similarity_entry_id,
            limit=limit,
            filters=filters or None,
        )
    elif q is not None:
        results = search_text(q, limit=limit, filters=filters or None)
    else:
        results = []

    return [
        SearchResultItem(
            id=uuid.UUID(r["entry_id"]),
            entry_id=uuid.UUID(r["entry_id"]),
            score=r["score"],
            title=r["payload"].get("title"),
            mood=r["payload"].get("mood"),
            location=r["payload"].get("location"),
            year=r["payload"].get("year"),
            month=r["payload"].get("month"),
        )
        for r in results
        if r.get("entry_id")
    ]


@app.get(
    "/api/entries/{entry_id}/similar",
    response_model=List[SearchResultItem],
    summary="Find diary entries with similar audio to the given entry",
)
def similar_audio(
    entry_id: uuid.UUID,
    limit: int = 10,
    year: Optional[int] = None,
    mood: Optional[str] = None,
):
    """
    Audio similarity search: find entries that sound similar to the given entry.
    Uses audio embedding vectors stored in Qdrant.
    """
    filters = {}
    if year is not None:
        filters["year"] = year
    if mood is not None:
        filters["mood"] = mood

    results = search_similar_audio(
        reference_entry_id=entry_id,
        limit=limit,
        filters=filters or None,
    )
    return [
        SearchResultItem(
            id=uuid.UUID(r["entry_id"]),
            entry_id=uuid.UUID(r["entry_id"]),
            score=r["score"],
            title=r["payload"].get("title"),
            mood=r["payload"].get("mood"),
            location=r["payload"].get("location"),
            year=r["payload"].get("year"),
            month=r["payload"].get("month"),
        )
        for r in results
        if r.get("entry_id")
    ]


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", summary="Health check")
def health():
    return {"status": "ok", "service": "sonochron-api"}


# ---------------------------------------------------------------------------
# Admin reset endpoint
# ---------------------------------------------------------------------------

@app.post(
    "/api/admin/reset",
    summary="Reset database and delete all rows in order of dependency",
)
def reset_database(session: Session = Depends(get_session)):
    """Deletes all rows in the PostgreSQL database in the correct dependency order,
    purges Qdrant collections, and clears physical storage files.
    """
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
        import logging
        logging.getLogger("sonochron.api").warning("Qdrant collections reset failed: %s", e)

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
        import logging
        logging.getLogger("sonochron.api").warning("Physical storage cleanup failed: %s", e)

    return {"status": "ok", "message": "Database, vector index, and storage reset successfully"}


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _entry_to_out(entry: DiaryEntry, session: Session) -> DiaryEntryOut:
    """Hydrate a DiaryEntry with its context and asset for API response."""
    context = entry.context
    asset = entry.asset

    context_out = None
    if context:
        context_out = EntryContextOut(
            mood=context.mood,
            location=context.location,
            companions=context.companions or [],
            notes=context.notes,
        )

    asset_out = None
    if asset:
        asset_out = SampleAssetOut(
            id=asset.id,
            filename=asset.filename,
            filepath=asset.filepath,
            checksum_sha256=getattr(asset, "checksum_sha256", None),
            duration_ms=getattr(asset, "duration_ms", None),
            byte_size=getattr(asset, "byte_size", None),
        )

    return DiaryEntryOut(
        id=entry.id,
        local_capture_time=entry.local_capture_time,
        utc_capture_time=getattr(entry, "utc_capture_time", None),
        title=getattr(entry, "title", None),
        stage=entry.stage,
        created_at=getattr(entry, "created_at", entry.local_capture_time),
        updated_at=getattr(entry, "updated_at", entry.local_capture_time),
        context=context_out,
        asset=asset_out,
    )


# ---------------------------------------------------------------------------
# Google Drive import endpoints
# ---------------------------------------------------------------------------

@app.get("/api/drive/status", summary="Drive auth status and sync state")
def drive_status():
    from app.drive import is_authenticated, get_sync_state, get_folder_id
    return {
        "authenticated": is_authenticated(),
        "folder_id": get_folder_id(),
        "sync": get_sync_state(),
    }


@app.get("/api/drive/auth", summary="Start Google OAuth2 flow")
def drive_auth():
    from fastapi.responses import RedirectResponse
    from app.drive import get_auth_url
    return RedirectResponse(url=get_auth_url())


@app.get("/api/drive/callback", summary="OAuth2 callback — exchanges code for tokens")
def drive_callback(code: str, state: Optional[str] = None):
    from fastapi.responses import RedirectResponse
    from app.drive import exchange_code
    try:
        exchange_code(code)
        return RedirectResponse(url="/?drive=connected")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"OAuth2 exchange failed: {exc}")


@app.get("/api/drive/files", summary="List audio files from Google Drive")
def drive_list_files():
    from app.drive import list_audio_files, is_authenticated
    if not is_authenticated():
        raise HTTPException(status_code=401, detail="Not authenticated with Google Drive")
    try:
        return list_audio_files()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/drive/import/{file_id}", summary="Import a single Drive file")
async def drive_import_file(file_id: str, filename: str = ""):
    from app.drive import is_authenticated, list_audio_files, _import_file_sync, get_imported_ids
    import asyncio
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
        return {"entry_id": entry_id, "status": "imported"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/drive/sync", summary="Manually trigger Drive auto-sync")
async def drive_sync():
    from app.drive import is_authenticated, run_auto_sync
    if not is_authenticated():
        raise HTTPException(status_code=401, detail="Not authenticated with Google Drive")
    count = await run_auto_sync()
    return {"imported": count}


@app.delete("/api/drive/auth", summary="Revoke Google Drive access")
def drive_revoke():
    from app.drive import revoke
    revoke()
    return {"status": "revoked"}

