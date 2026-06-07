"""
pipeline.py — Stage-based processing pipeline for Sonochron.

Each diary entry passes through explicit stages stored in Postgres.
All ML stages now use real models via app.ml.

Stages (in order):
  uploaded → validated → speech_detected → transcribed →
  text_embedded → audio_embedded → indexed → ready

On any unrecoverable error the entry is marked: failed
"""

import asyncio
import uuid
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlmodel import Session, select

from app.database import engine, DiaryEntry, SampleAsset

logger = logging.getLogger("sonochron.pipeline")

# ---------------------------------------------------------------------------
# Stage constants — must match DiaryEntry.stage values
# ---------------------------------------------------------------------------
STAGES = [
    "uploaded",
    "validated",
    "speech_detected",
    "transcribed",
    "text_embedded",
    "audio_embedded",
    "indexed",
    "ready",
]
STAGE_FAILED = "failed"

# Storage base dir (must match main.py / LocalStorageProvider)
_STORAGE_BASE = "backend/storage/raw"


def _resolve_audio_path(asset_filepath: str) -> str:
    """Resolve a storage key to an absolute path on disk."""
    p = Path(_STORAGE_BASE) / asset_filepath
    return str(p)


def _advance_stage(session: Session, entry: DiaryEntry, next_stage: str) -> None:
    """Update entry stage and updated_at timestamp."""
    entry.stage = next_stage
    entry.updated_at = datetime.utcnow()
    session.add(entry)
    session.commit()
    session.refresh(entry)
    logger.info("Entry %s advanced to stage: %s", entry.id, next_stage)


def _mark_failed(session: Session, entry: DiaryEntry, reason: str) -> None:
    """Mark entry as failed with logging."""
    entry.stage = STAGE_FAILED
    entry.updated_at = datetime.utcnow()
    session.add(entry)
    session.commit()
    logger.error("Entry %s failed: %s", entry.id, reason)


# ---------------------------------------------------------------------------
# Individual stage processors (synchronous, run inside thread)
# ---------------------------------------------------------------------------

def _stage_validate(session: Session, entry: DiaryEntry) -> bool:
    """
    Stage: validated
    Checks that the SampleAsset exists and has non-zero byte_size.
    """
    asset = session.exec(
        select(SampleAsset).where(SampleAsset.entry_id == entry.id)
    ).first()

    if not asset:
        _mark_failed(session, entry, "No SampleAsset found for entry.")
        return False

    byte_size = getattr(asset, "byte_size", None)
    if byte_size is not None and byte_size == 0:
        _mark_failed(session, entry, "Empty audio file — byte_size is 0.")
        return False

    _advance_stage(session, entry, "validated")
    return True


def _stage_detect_speech(session: Session, entry: DiaryEntry) -> bool:
    """
    Stage: speech_detected
    Uses Whisper to check for audible content.
    A non-empty transcript is treated as speech detected.
    Falls back to True on model errors (non-fatal heuristic).
    """
    from app.database import EntryContext

    asset = session.exec(
        select(SampleAsset).where(SampleAsset.entry_id == entry.id)
    ).first()

    if not asset:
        # No asset — can't detect speech, proceed anyway
        _advance_stage(session, entry, "speech_detected")
        return True

    audio_path = _resolve_audio_path(asset.filepath)
    if not Path(audio_path).exists():
        logger.warning("Audio file not found at %s — skipping speech detection", audio_path)
        _advance_stage(session, entry, "speech_detected")
        return True

    try:
        from app.ml import transcribe_audio
        transcript = transcribe_audio(audio_path)
        # Store transcript in EntryContext notes if no notes yet
        context = session.exec(
            select(EntryContext).where(EntryContext.entry_id == entry.id)
        ).first()
        if context and not context.notes and transcript:
            context.notes = f"[Transcript] {transcript}"
            session.add(context)
            session.commit()
        # Store transcript on entry for later re-use
        entry._whisper_transcript = transcript  # transient attr for pipeline use
        speech_detected = bool(transcript.strip())
        logger.info(
            "Speech detection for entry %s: %s (transcript length: %d)",
            entry.id, speech_detected, len(transcript)
        )
    except Exception as exc:
        logger.warning("Speech detection error for entry %s: %s — assuming speech present", entry.id, exc)

    _advance_stage(session, entry, "speech_detected")
    return True


def _stage_transcribe(session: Session, entry: DiaryEntry) -> bool:
    """
    Stage: transcribed
    Runs Whisper on the audio file to produce a transcript.
    The transcript is stored as a prefix in EntryContext.notes
    if the user hasn't provided notes (non-destructive).
    """
    from app.database import EntryContext

    asset = session.exec(
        select(SampleAsset).where(SampleAsset.entry_id == entry.id)
    ).first()

    if not asset:
        _advance_stage(session, entry, "transcribed")
        return True

    audio_path = _resolve_audio_path(asset.filepath)
    if not Path(audio_path).exists():
        logger.warning("Audio file missing for transcription: %s", audio_path)
        _advance_stage(session, entry, "transcribed")
        return True

    try:
        from app.ml import transcribe_audio
        transcript = transcribe_audio(audio_path)

        # Persist transcript: prepend to context.notes if currently empty or
        # transcript marker not already there
        context = session.exec(
            select(EntryContext).where(EntryContext.entry_id == entry.id)
        ).first()
        if context and transcript:
            marker = "[Transcript] "
            existing = context.notes or ""
            if marker not in existing:
                if existing:
                    context.notes = f"{marker}{transcript}\n\n{existing}"
                else:
                    context.notes = f"{marker}{transcript}"
                session.add(context)
                session.commit()

        # Auto-generate title from transcript if none set
        if not entry.title and transcript:
            # Use the first ~60 chars of transcript as a working title
            words = transcript.strip().split()
            snippet = " ".join(words[:10])
            if len(snippet) > 60:
                snippet = snippet[:57] + "…"
            entry.title = snippet
            session.add(entry)
            session.commit()

        logger.info("Transcription stored for entry %s (%d chars)", entry.id, len(transcript))
    except Exception as exc:
        logger.error("Transcription stage failed for entry %s: %s", entry.id, exc)
        # Non-fatal: continue pipeline

    _advance_stage(session, entry, "transcribed")
    return True


def _stage_text_embed(session: Session, entry: DiaryEntry) -> bool:
    """
    Stage: text_embedded
    Generates a real 384-dim text embedding using sentence-transformers
    (all-MiniLM-L6-v2). The vector is stored in Qdrant during the index stage.
    """
    from app.database import EntryContext

    context = session.exec(
        select(EntryContext).where(EntryContext.entry_id == entry.id)
    ).first()

    # Build the text to embed
    text_parts = []
    if entry.title:
        text_parts.append(entry.title)
    if context:
        if context.notes:
            text_parts.append(context.notes)
        if context.mood:
            text_parts.append(f"mood:{context.mood}")
        if context.location:
            text_parts.append(f"location:{context.location}")
        if context.companions:
            text_parts.append(" ".join(context.companions))
    text_content = " ".join(text_parts) or f"entry:{entry.id}"

    try:
        from app.ml import embed_text, embed_text_sparse
        vec = embed_text(text_content)
        sparse_vec = embed_text_sparse(text_content)
        logger.info(
            "Text embedding generated for entry %s (dim=%d, norm=%.4f, sparse_terms=%d)",
            entry.id, len(vec), sum(x**2 for x in vec)**0.5, len(sparse_vec.get("indices", []))
        )
        # Stash on entry for use in index stage
        entry._text_vector = vec
        entry._text_content = text_content
        entry._sparse_vector = sparse_vec
    except Exception as exc:
        logger.error("Text embedding failed for entry %s: %s", entry.id, exc)
        entry._text_vector = [0.0] * 384
        entry._text_content = text_content
        entry._sparse_vector = {"indices": [], "values": []}

    _advance_stage(session, entry, "text_embedded")
    return True


def _stage_audio_embed(session: Session, entry: DiaryEntry) -> bool:
    """
    Stage: audio_embedded
    Generates a real 1024-dim audio embedding using CLAP (laion/larger_clap_general).
    The vector is stored in Qdrant during the index stage.
    """
    asset = session.exec(
        select(SampleAsset).where(SampleAsset.entry_id == entry.id)
    ).first()

    audio_path = _resolve_audio_path(asset.filepath) if asset else ""

    try:
        from app.ml import embed_audio
        vec = embed_audio(audio_path)
        logger.info(
            "Audio embedding generated for entry %s (dim=%d, norm=%.4f)",
            entry.id, len(vec), sum(x**2 for x in vec)**0.5
        )
        entry._audio_vector = vec
    except Exception as exc:
        logger.error("Audio embedding failed for entry %s: %s", entry.id, exc)
        entry._audio_vector = [0.0] * 1024

    _advance_stage(session, entry, "audio_embedded")
    return True


def _stage_index(session: Session, entry: DiaryEntry) -> bool:
    """
    Stage: indexed
    Upserts text and audio vectors into local Qdrant collections.
    Uses real vectors stashed on the entry object by previous stages.
    Falls back to recomputing if vectors weren't stashed (e.g. pipeline resumed).
    """
    from app.database import EntryContext, SampleAsset
    from app.search import upsert_entry, _build_entry_payload

    context = session.exec(
        select(EntryContext).where(EntryContext.entry_id == entry.id)
    ).first()
    asset = session.exec(
        select(SampleAsset).where(SampleAsset.entry_id == entry.id)
    ).first()
    audio_filepath = asset.filepath if asset else ""
    audio_path = _resolve_audio_path(audio_filepath) if audio_filepath else ""
    payload = _build_entry_payload(entry, context)

    # Build text content
    text_parts = []
    if entry.title:
        text_parts.append(entry.title)
    if context:
        if context.notes:
            text_parts.append(context.notes)
        if context.mood:
            text_parts.append(f"mood:{context.mood}")
        if context.location:
            text_parts.append(f"location:{context.location}")
        if context.companions:
            text_parts.append(" ".join(context.companions))
    text_content = " ".join(text_parts) or f"entry:{entry.id}"

    # Retrieve or recompute vectors
    text_vec = getattr(entry, "_text_vector", None)
    audio_vec = getattr(entry, "_audio_vector", None)
    sparse_vec = getattr(entry, "_sparse_vector", None)

    if text_vec is None:
        from app.ml import embed_text
        text_vec = embed_text(text_content)

    if audio_vec is None:
        from app.ml import embed_audio
        audio_vec = embed_audio(audio_path)

    if sparse_vec is None:
        from app.ml import embed_text_sparse
        sparse_vec = embed_text_sparse(text_content)

    try:
        upsert_entry(
            entry_id=entry.id,
            text_content=text_content,
            audio_filepath=audio_filepath,
            payload=payload,
            text_vector=text_vec,
            audio_vector=audio_vec,
            sparse_vector=sparse_vec,
        )
        logger.info("Qdrant upsert complete for entry %s (named+sparse)", entry.id)
    except Exception as exc:
        logger.error("Qdrant upsert failed for entry %s: %s", entry.id, exc)
        # Non-fatal: Qdrant is derivable — log but don't fail the pipeline

    _advance_stage(session, entry, "indexed")
    return True


def _stage_ready(session: Session, entry: DiaryEntry) -> bool:
    """
    Stage: ready — final stage indicating full pipeline completion.
    """
    _advance_stage(session, entry, "ready")
    logger.info("Entry %s is fully processed and ready.", entry.id)
    return True


# ---------------------------------------------------------------------------
# Pipeline runner (synchronous, called inside asyncio executor)
# ---------------------------------------------------------------------------

STAGE_PROCESSORS = [
    ("validated", _stage_validate),
    ("speech_detected", _stage_detect_speech),
    ("transcribed", _stage_transcribe),
    ("text_embedded", _stage_text_embed),
    ("audio_embedded", _stage_audio_embed),
    ("indexed", _stage_index),
    ("ready", _stage_ready),
]


def _run_pipeline(entry_id: uuid.UUID) -> None:
    """
    Run the full processing pipeline for a diary entry.
    Each stage is independent — if one fails, the entry is marked failed
    and subsequent stages are skipped.
    """
    with Session(engine) as session:
        entry = session.get(DiaryEntry, entry_id)
        if not entry:
            logger.error("Pipeline: entry %s not found in database.", entry_id)
            return

        logger.info("Pipeline starting for entry %s (current stage: %s)", entry_id, entry.stage)

        for stage_name, processor in STAGE_PROCESSORS:
            # Skip stages we've already passed
            current_idx = STAGES.index(entry.stage) if entry.stage in STAGES else -1
            target_idx = STAGES.index(stage_name) if stage_name in STAGES else -1

            if current_idx >= target_idx:
                continue  # Already at or past this stage

            if entry.stage == STAGE_FAILED:
                logger.warning("Pipeline halted for entry %s — entry is in failed state.", entry_id)
                return

            try:
                success = processor(session, entry)
                if not success:
                    return
            except Exception as exc:
                logger.exception("Unhandled exception in stage %s for entry %s", stage_name, entry_id)
                _mark_failed(session, entry, f"Exception in {stage_name}: {exc}")
                return


# ---------------------------------------------------------------------------
# Async entry point called from FastAPI after ingestion
# ---------------------------------------------------------------------------

async def enqueue_processing(entry_id: uuid.UUID) -> None:
    """
    Enqueue the processing pipeline as a background asyncio task.
    Uses run_in_executor so the synchronous DB calls don't block the event loop.
    """
    loop = asyncio.get_event_loop()
    asyncio.ensure_future(
        loop.run_in_executor(None, _run_pipeline, entry_id)
    )
    logger.info("Enqueued processing pipeline for entry %s", entry_id)
