"""
search.py — Qdrant local-filesystem vector search for Sonochron.

Qdrant runs in local mode (no server process needed) using a persistent
directory on disk. Two collections are maintained:

  sonochron_text  — named dense vector "text" (384-dim, cosine) +
                    named sparse vector "text_sparse" (BM25-style, dot)
                    → used for hybrid search via RRF fusion
  sonochron_audio — named dense vector "audio" (512-dim, cosine)
                    → used for audio similarity search

FIX 1: All vectors are now NAMED — required by the model-migration skill to
        enable zero-downtime CLAP/PANNs swap without recreating collections.
        (qdrant-client 1.18+ supports UpdateVectors for named fields.)

FIX 2: HYBRID SEARCH — search_text() runs dense + sparse prefetches fused
        via RRF (Reciprocal Rank Fusion). Per the combining-searches skill:
        "Scores are not comparable across prefetches" — use RRF as baseline.
        Falls back to dense-only if sparse vector is empty.

FIX 3: BATCH UPSERTS in reindex_all() — uses client.upload_points() instead
        of one-at-a-time upserts. Per the clients-sdk skill, upload_points()
        supports parallel streams for faster bulk ingestion.

Migration: If collections exist with old unnamed-vector format, they are
           detected and dropped automatically. Run `python -m app.cli reindex`
           after restart to repopulate.

Both collections are keyed by diary entry UUID (as int). Search results always
return entry IDs which map back to canonical Postgres records.
"""

import uuid
import logging
import math
import re
from pathlib import Path
from typing import Optional, List, Dict, Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    SparseVectorParams,
    SparseVector,
    SparseIndexParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
    ScoredPoint,
    Prefetch,
    Fusion,
    PayloadSchemaType,
)

logger = logging.getLogger("sonochron.search")

# --- Dimensions (must match app.ml model output dims) ---
TEXT_DIM = 384    # sentence-transformers all-MiniLM-L6-v2
AUDIO_DIM = 1024  # CLAP laion/larger_clap_general (2023 version)

# --- Collection names ---
TEXT_COLLECTION = "sonochron_text"
AUDIO_COLLECTION = "sonochron_audio"

# --- Named vector keys (FIX 1) ---
# Using named vectors enables zero-downtime model migration via v1.18+ UpdateVectors.
# The model-migration skill: "If collection has named vectors on v1.18+, add new vector
# field directly without recreating collection."
TEXT_VECTOR_NAME = "text"           # 384-dim dense semantic vector
TEXT_SPARSE_NAME = "text_sparse"    # sparse BM25-style vector for hybrid search
AUDIO_VECTOR_NAME = "audio"         # 1024-dim CLAP neural audio embedding

# --- Batch size for reindex_all (FIX 3) ---
REINDEX_BATCH_SIZE = 64


_client: Optional["QdrantClient"] = None
_client_path: Optional[str] = None


def _get_client(storage_path: str = "backend/qdrant_storage") -> "QdrantClient":
    """Return the shared module-level Qdrant client singleton."""
    global _client, _client_path
    if _client is None or _client_path != storage_path:
        Path(storage_path).mkdir(parents=True, exist_ok=True)
        _client = QdrantClient(path=storage_path)
        _client_path = storage_path
        logger.info("Qdrant local client opened at: %s", storage_path)
    return _client


def _collection_needs_migration(client: "QdrantClient", collection_name: str) -> bool:
    """
    Return True if a collection exists with old unnamed-vector format.

    Named vector collections have a dict for `vectors_config`; old unnamed
    collections have a single VectorParams object. Per the model-migration
    skill: old unnamed format blocks zero-downtime model updates.
    """
    try:
        info = client.get_collection(collection_name)
        vectors = info.config.params.vectors
        # Named vectors → dict. Unnamed vector → VectorParams object.
        is_unnamed = not isinstance(vectors, dict)
        if is_unnamed:
            logger.info(
                "Collection '%s' uses old unnamed vectors — will migrate to named",
                collection_name,
            )
        return is_unnamed
    except Exception:
        # Collection doesn't exist yet — no migration needed
        return False


def ensure_collections(storage_path: str = "backend/qdrant_storage") -> None:
    """
    Create Qdrant collections with named vectors if they don't already exist.

    Migrates old unnamed-vector collections automatically by dropping and
    recreating them. Run `python -m app.cli reindex` after migration to
    repopulate from Postgres.

    Also creates payload indexes on filterable fields (year, month, mood,
    location, stage) per the search-speed-optimization skill: "Create payload
    index on the filtered field — most common fix for slow filtered search."
    """
    client = _get_client(storage_path)
    existing = {c.name for c in client.get_collections().collections}

    # --- Migrate old unnamed collections or wrong-dim audio collection ---
    for coll in (TEXT_COLLECTION, AUDIO_COLLECTION):
        if coll in existing and _collection_needs_migration(client, coll):
            logger.warning(
                "Dropping collection '%s' (unnamed → named vector migration). "
                "Run `python -m app.cli reindex` to repopulate.",
                coll,
            )
            client.delete_collection(coll)
            existing.discard(coll)

    # Auto-drop audio collection if it exists with wrong dim (e.g. old 512 → new 1024)
    if AUDIO_COLLECTION in existing:
        try:
            info = client.get_collection(AUDIO_COLLECTION)
            vectors_cfg = info.config.params.vectors
            if isinstance(vectors_cfg, dict) and AUDIO_VECTOR_NAME in vectors_cfg:
                actual_dim = vectors_cfg[AUDIO_VECTOR_NAME].size
                if actual_dim != AUDIO_DIM:
                    logger.warning(
                        "Audio collection dim mismatch (stored=%d, expected=%d) — "
                        "dropping and recreating. Run `python -m app.cli reindex`.",
                        actual_dim, AUDIO_DIM,
                    )
                    client.delete_collection(AUDIO_COLLECTION)
                    existing.discard(AUDIO_COLLECTION)
        except Exception as exc:
            logger.warning("Could not inspect audio collection dims: %s", exc)

    # --- Create sonochron_text with named dense + sparse vectors (FIX 1 + 2) ---
    if TEXT_COLLECTION not in existing:
        client.create_collection(
            collection_name=TEXT_COLLECTION,
            vectors_config={
                TEXT_VECTOR_NAME: VectorParams(
                    size=TEXT_DIM, distance=Distance.COSINE
                )
            },
            sparse_vectors_config={
                TEXT_SPARSE_NAME: SparseVectorParams(
                    index=SparseIndexParams(on_disk=False)
                )
            },
        )
        # Payload indexes for filtered search (search-speed-optimization skill)
        for field in ("year", "month", "stage", "mood", "location"):
            client.create_payload_index(
                collection_name=TEXT_COLLECTION,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )
        logger.info("Created Qdrant collection: %s (named dense + sparse)", TEXT_COLLECTION)

    # --- Create sonochron_audio with named dense vector (FIX 1) ---
    if AUDIO_COLLECTION not in existing:
        client.create_collection(
            collection_name=AUDIO_COLLECTION,
            vectors_config={
                AUDIO_VECTOR_NAME: VectorParams(
                    size=AUDIO_DIM, distance=Distance.COSINE
                )
            },
        )
        for field in ("year", "month", "stage"):
            client.create_payload_index(
                collection_name=AUDIO_COLLECTION,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )
        logger.info("Created Qdrant collection: %s (named dense)", AUDIO_COLLECTION)


# ---------------------------------------------------------------------------
# Vector generators
# ---------------------------------------------------------------------------

def _text_vector(text: str) -> List[float]:
    """384-dim text embedding via sentence-transformers (all-MiniLM-L6-v2)."""
    from app.ml import embed_text
    return embed_text(text)


def _audio_vector(filepath: str) -> List[float]:
    """1024-dim CLAP neural audio embedding (laion/larger_clap_general)."""
    from app.ml import embed_audio
    return embed_audio(filepath)


def _sparse_vector(text: str) -> Dict[str, Any]:
    """
    BM25-style sparse vector for hybrid text search (FIX 2).

    Tokenises text, applies log-TF weighting, and maps each unique term to an
    index via a stable hash. No external vocabulary or model needed.

    Returns: {"indices": List[int], "values": List[float]}
    Compatible with Qdrant SparseVector(indices=..., values=...).

    Per the search-types skill: "BM25 — good baseline, works out-of-domain,
    usually for long texts." This client-side implementation mirrors BM25 TF
    weighting without requiring the server-side BM25 plugin.
    """
    from app.ml import embed_text_sparse
    return embed_text_sparse(text)


# ---------------------------------------------------------------------------
# Upsert (index) an entry
# ---------------------------------------------------------------------------

def upsert_entry(
    entry_id: uuid.UUID,
    text_content: str,
    audio_filepath: str,
    payload: Dict[str, Any],
    storage_path: str = "backend/qdrant_storage",
    text_vector: Optional[List[float]] = None,
    audio_vector: Optional[List[float]] = None,
    sparse_vector: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Upsert text and audio vectors for a diary entry into Qdrant.

    FIX 1: Vectors stored under named keys (TEXT_VECTOR_NAME, AUDIO_VECTOR_NAME,
    TEXT_SPARSE_NAME) — required for zero-downtime model migration.

    FIX 2: sparse_vector stored alongside dense text vector to enable hybrid
    search via RRF fusion in search_text().

    Args:
        entry_id:      Canonical Postgres diary entry UUID
        text_content:  Merged text for semantic search
        audio_filepath: Storage key for the raw audio file
        payload:       Dict of filterable metadata (year, month, mood, etc.)
        storage_path:  Path to local Qdrant storage directory
        text_vector:   Pre-computed 384-dim dense embedding (computed if None)
        audio_vector:  Pre-computed 512-dim audio embedding (computed if None)
        sparse_vector: Pre-computed sparse dict with 'indices'/'values' (computed if None)
    """
    ensure_collections(storage_path)
    client = _get_client(storage_path)

    point_id = str(entry_id)

    # Compute vectors if not pre-supplied
    text_vec = text_vector if text_vector is not None else _text_vector(text_content)
    sparse_vec = sparse_vector if sparse_vector is not None else _sparse_vector(text_content)

    audio_disk_path = ""
    if audio_filepath:
        candidate = Path("backend/storage/raw") / audio_filepath
        audio_disk_path = str(candidate) if candidate.exists() else audio_filepath
    audio_vec = audio_vector if audio_vector is not None else _audio_vector(audio_disk_path)

    full_payload = {"entry_id": str(entry_id), **payload}

    # Build text point with named dense + sparse vectors
    text_named_vectors: Dict[str, Any] = {TEXT_VECTOR_NAME: text_vec}
    if sparse_vec.get("indices"):
        text_named_vectors[TEXT_SPARSE_NAME] = SparseVector(
            indices=sparse_vec["indices"],
            values=sparse_vec["values"],
        )

    client.upsert(
        collection_name=TEXT_COLLECTION,
        points=[PointStruct(id=point_id, vector=text_named_vectors, payload=full_payload)],
    )
    client.upsert(
        collection_name=AUDIO_COLLECTION,
        points=[PointStruct(
            id=point_id,
            vector={AUDIO_VECTOR_NAME: audio_vec},
            payload=full_payload,
        )],
    )
    logger.info("Upserted entry %s into Qdrant text+audio collections (named+sparse)", entry_id)


# ---------------------------------------------------------------------------
# Delete an entry from the index
# ---------------------------------------------------------------------------

def delete_entry(
    entry_id: uuid.UUID,
    storage_path: str = "backend/qdrant_storage",
) -> None:
    """Remove an entry's vectors from both Qdrant collections."""
    client = _get_client(storage_path)
    point_id = str(entry_id)
    for collection in (TEXT_COLLECTION, AUDIO_COLLECTION):
        client.delete(collection_name=collection, points_selector=[point_id])
    logger.info("Deleted entry %s from Qdrant", entry_id)


# ---------------------------------------------------------------------------
# Text semantic search — hybrid dense + sparse RRF (FIX 2)
# ---------------------------------------------------------------------------

def search_text(
    query: str,
    limit: int = 10,
    filters: Optional[Dict[str, Any]] = None,
    storage_path: str = "backend/qdrant_storage",
) -> List[Dict[str, Any]]:
    """
    Search diary entries by hybrid text similarity (dense + sparse via RRF).

    FIX 2: Uses prefetch-based hybrid search with Reciprocal Rank Fusion (RRF).
    Per the combining-searches skill: "Scores are not comparable across
    prefetches — RRF is a decent default to start with."

    Prefetch[0]: dense cosine search on TEXT_VECTOR_NAME (semantic)
    Prefetch[1]: sparse dot-product search on TEXT_SPARSE_NAME (lexical/BM25)
    Outer query: Fusion.RRF merges ranked candidate lists

    Falls back to dense-only if sparse vector is empty (e.g. no text to tokenise).

    Returns a list of dicts with keys: entry_id, score, payload.
    """
    ensure_collections(storage_path)
    client = _get_client(storage_path)

    query_vec = _text_vector(query)
    sparse_vec = _sparse_vector(query)
    qdrant_filter = _build_filter(filters) if filters else None

    # Prefetch pool is larger than final limit — RRF re-ranks from the union
    prefetch_limit = limit * 3

    try:
        if sparse_vec.get("indices"):
            # Hybrid search: dense + sparse → RRF fusion
            response = client.query_points(
                collection_name=TEXT_COLLECTION,
                prefetch=[
                    Prefetch(
                        query=query_vec,
                        using=TEXT_VECTOR_NAME,
                        limit=prefetch_limit,
                        filter=qdrant_filter,
                    ),
                    Prefetch(
                        query=SparseVector(
                            indices=sparse_vec["indices"],
                            values=sparse_vec["values"],
                        ),
                        using=TEXT_SPARSE_NAME,
                        limit=prefetch_limit,
                        filter=qdrant_filter,
                    ),
                ],
                query=Fusion.RRF,
                limit=limit,
                with_payload=True,
            )
            logger.debug("Hybrid (dense+sparse RRF) search returned %d results", len(response.points))
        else:
            raise ValueError("Sparse vector is empty — falling back to dense-only")

    except Exception as exc:
        # Graceful fallback: dense-only search (e.g. before sparse vectors are indexed,
        # or on empty queries). This keeps the API working during progressive reindex.
        logger.info("Falling back to dense-only search: %s", exc)
        response = client.query_points(
            collection_name=TEXT_COLLECTION,
            query=query_vec,
            using=TEXT_VECTOR_NAME,
            limit=limit,
            query_filter=qdrant_filter,
            with_payload=True,
        )

    return [
        {
            "entry_id": r.payload.get("entry_id"),
            "score": r.score,
            "payload": r.payload,
        }
        for r in response.points
    ]


# ---------------------------------------------------------------------------
# Audio similarity search
# ---------------------------------------------------------------------------

def search_similar_audio(
    reference_entry_id: uuid.UUID,
    limit: int = 10,
    filters: Optional[Dict[str, Any]] = None,
    storage_path: str = "backend/qdrant_storage",
) -> List[Dict[str, Any]]:
    """
    Find diary entries with audio similar to the given reference entry.

    FIX 1: Uses `using=AUDIO_VECTOR_NAME` to query the named audio vector.
    """
    ensure_collections(storage_path)
    client = _get_client(storage_path)
    point_id = str(reference_entry_id)

    # Fetch the reference vector by its point ID
    ref_response = client.retrieve(
        collection_name=AUDIO_COLLECTION,
        ids=[point_id],
        with_vectors=True,
    )
    if not ref_response:
        logger.warning("No audio vector found for entry %s", reference_entry_id)
        return []

    # Extract named vector
    ref_vectors = ref_response[0].vector
    if isinstance(ref_vectors, dict):
        ref_vector = ref_vectors.get(AUDIO_VECTOR_NAME, [])
    else:
        ref_vector = ref_vectors  # fallback for unnamed (shouldn't happen post-migration)

    qdrant_filter = _build_filter(filters) if filters else None

    response = client.query_points(
        collection_name=AUDIO_COLLECTION,
        query=ref_vector,
        using=AUDIO_VECTOR_NAME,
        limit=limit + 1,
        query_filter=qdrant_filter,
        with_payload=True,
    )

    return [
        {
            "entry_id": r.payload.get("entry_id"),
            "score": r.score,
            "payload": r.payload,
        }
        for r in response.points
        if r.id != point_id
    ][:limit]


# ---------------------------------------------------------------------------
# Full reindex from Postgres records — batch upload (FIX 3)
# ---------------------------------------------------------------------------

def reindex_all(
    storage_path: str = "backend/qdrant_storage",
) -> int:
    """
    Rebuild the entire Qdrant index from Postgres state.

    FIX 3: Uses client.upload_points() in batches (REINDEX_BATCH_SIZE) instead
    of one upsert per entry. Per the clients-sdk skill, upload_points() with
    parallel streams significantly speeds up bulk ingestion.

    Drops both collections, recreates them, then re-upserts every
    diary entry that has reached the 'ready' stage.

    Returns the number of entries re-indexed.
    """
    from sqlmodel import Session, select
    from app.database import engine, DiaryEntry, EntryContext, SampleAsset

    client = _get_client(storage_path)

    # Drop and recreate collections (ensures fresh named-vector schema)
    for collection in (TEXT_COLLECTION, AUDIO_COLLECTION):
        try:
            client.delete_collection(collection)
            logger.info("Dropped Qdrant collection: %s", collection)
        except Exception:
            pass
    ensure_collections(storage_path)

    text_points: List[PointStruct] = []
    audio_points: List[PointStruct] = []
    count = 0

    def _flush_batches(force: bool = False) -> None:
        """Upload accumulated points when batch is full or force=True."""
        nonlocal text_points, audio_points
        if not force and len(text_points) < REINDEX_BATCH_SIZE:
            return
        if text_points:
            client.upload_points(
                collection_name=TEXT_COLLECTION,
                points=text_points,
                parallel=2,
                max_retries=3,
            )
            logger.debug("Batch-uploaded %d text points", len(text_points))
            text_points = []
        if audio_points:
            client.upload_points(
                collection_name=AUDIO_COLLECTION,
                points=audio_points,
                parallel=2,
                max_retries=3,
            )
            logger.debug("Batch-uploaded %d audio points", len(audio_points))
            audio_points = []

    with Session(engine) as session:
        entries = session.exec(
            select(DiaryEntry).where(DiaryEntry.stage == "ready")
        ).all()

        for entry in entries:
            context = session.exec(
                select(EntryContext).where(EntryContext.entry_id == entry.id)
            ).first()
            asset = session.exec(
                select(SampleAsset).where(SampleAsset.entry_id == entry.id)
            ).first()

            # Build merged text for semantic + sparse indexing
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
            text_content = " ".join(text_parts) or f"entry:{entry.id}"

            audio_filepath = asset.filepath if asset else ""
            audio_disk_path = ""
            if audio_filepath:
                candidate = Path("backend/storage/raw") / audio_filepath
                audio_disk_path = str(candidate) if candidate.exists() else audio_filepath

            payload = _build_entry_payload(entry, context)
            full_payload = {"entry_id": str(entry.id), **payload}
            point_id = str(entry.id)

            # Compute vectors
            text_vec = _text_vector(text_content)
            sparse_vec = _sparse_vector(text_content)
            audio_vec = _audio_vector(audio_disk_path)

            # Build named-vector point structs
            text_named: Dict[str, Any] = {TEXT_VECTOR_NAME: text_vec}
            if sparse_vec.get("indices"):
                text_named[TEXT_SPARSE_NAME] = SparseVector(
                    indices=sparse_vec["indices"],
                    values=sparse_vec["values"],
                )

            text_points.append(PointStruct(
                id=point_id,
                vector=text_named,
                payload=full_payload,
            ))
            audio_points.append(PointStruct(
                id=point_id,
                vector={AUDIO_VECTOR_NAME: audio_vec},
                payload=full_payload,
            ))
            count += 1
            _flush_batches()

        # Final flush
        _flush_batches(force=True)

    logger.info("Reindex complete: %d entries indexed (batch size=%d)", count, REINDEX_BATCH_SIZE)
    return count


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_entry_payload(entry: Any, context: Any) -> Dict[str, Any]:
    """Build a filterable Qdrant payload from a DiaryEntry + EntryContext."""
    import datetime
    capture = entry.local_capture_time
    return {
        "year": str(capture.year) if capture else None,
        "month": str(capture.month) if capture else None,
        "stage": entry.stage,
        "title": entry.title,
        "mood": context.mood if context else None,
        "location": context.location if context else None,
        "companions": context.companions if context else [],
    }


def _build_filter(filters: Dict[str, Any]) -> Optional[Filter]:
    """Convert a plain dict of field→value pairs into a Qdrant Filter."""
    conditions = []
    for field, value in filters.items():
        if value is not None:
            conditions.append(
                FieldCondition(key=field, match=MatchValue(value=str(value)))
            )
    if not conditions:
        return None
    return Filter(must=conditions)
