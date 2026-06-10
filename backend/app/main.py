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
    DiaryEntry,
    EntryContext,
    SampleAsset,
    IdempotencyKey,
    YearArchive,
    MonthArchive,
)
from app.search import search_text, search_similar_audio, ensure_collections


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB tables and Qdrant collections on startup and start background loop."""
    init_db()
    ensure_collections()

    # Start Drive auto-sync background loop
    from app.services.drive_service import start_drive_sync_loop
    start_drive_sync_loop()
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
    from app.services import timeline_service
    content = await file.read()
    entry = await timeline_service.create_diary_entry(
        session=session,
        filename=file.filename,
        content=content,
        local_capture_time=local_capture_time,
        title=title,
        mood=mood,
        location=location,
        companions=companions,
        notes=notes,
        x_idempotency_key=x_idempotency_key,
    )
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
    from app.services import timeline_service
    return timeline_service.get_timeline_hierarchy(session)


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
    from app.services import timeline_service
    entries = timeline_service.list_diary_entries(
        session=session,
        year=year,
        month=month,
        limit=limit,
        offset=offset,
    )
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
    from app.services import timeline_service
    entry = timeline_service.get_diary_entry(session, entry_id)
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
    from app.services import timeline_service
    entry = timeline_service.get_diary_entry(session, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found.")

    asset = timeline_service.get_diary_entry_asset(session, entry_id)
    if not asset:
        raise HTTPException(status_code=404, detail="No audio asset for this entry.")

    from app.services.timeline_service import storage
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
    from app.services import timeline_service
    entry = timeline_service.get_diary_entry(session, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found.")

    asset = timeline_service.get_diary_entry_asset(session, entry_id)
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
    from app.services import timeline_service
    patch_data = patch.model_dump(exclude_unset=True)
    entry = timeline_service.update_diary_entry(session, entry_id, patch_data)
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
    from app.services import timeline_service
    await timeline_service.delete_diary_entry(session, entry_id)


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
    from app.services import timeline_service
    timeline_service.reset_system(session)
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
    from app.services import drive_service
    return drive_service.get_drive_status()


@app.get("/api/drive/auth", summary="Start Google OAuth2 flow")
def drive_auth():
    from fastapi.responses import RedirectResponse
    from app.services import drive_service
    return RedirectResponse(url=drive_service.get_auth_url())


@app.get("/api/drive/callback", summary="OAuth2 callback — exchanges code for tokens")
def drive_callback(code: str, state: Optional[str] = None):
    from fastapi.responses import RedirectResponse
    from app.services import drive_service
    try:
        drive_service.exchange_code(code)
        return RedirectResponse(url="/?drive=connected")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"OAuth2 exchange failed: {exc}")


@app.get("/api/drive/files", summary="List audio files from Google Drive")
def drive_list_files():
    from app.services import drive_service
    return drive_service.list_drive_files()


@app.post("/api/drive/import/{file_id}", summary="Import a single Drive file")
async def drive_import_file(file_id: str, filename: str = ""):
    from app.services import drive_service
    entry_id = await drive_service.import_drive_file(file_id, filename)
    return {"entry_id": entry_id, "status": "imported"}


@app.post("/api/drive/sync", summary="Manually trigger Drive auto-sync")
async def drive_sync():
    from app.services import drive_service
    count = await drive_service.trigger_sync()
    return {"imported": count}


@app.delete("/api/drive/auth", summary="Revoke Google Drive access")
def drive_revoke():
    from app.services import drive_service
    drive_service.revoke_access()
    return {"status": "revoked"}
