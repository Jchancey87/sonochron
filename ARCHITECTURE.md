# Sonochron — Architecture

## Overview

Sonochron is a self-hosted personal sound diary running on a Proxmox LXC container (IP `192.168.0.204`). It follows a **capture → context → search** model: audio is ingested instantly and processed asynchronously through a real ML pipeline.

---

## Component diagram

```
┌─────────────────────────────────────────────────────────┐
│  Browser  (http://192.168.0.204:5173)                   │
│                                                         │
│  React 18 + TypeScript + Vite (production build)        │
│  Views: Capture · Timeline · Search                     │
└────────────────────┬────────────────────────────────────┘
                     │ HTTP (CORS: 192.168.0.204:5173 only)
                     ▼
┌─────────────────────────────────────────────────────────┐
│  FastAPI  :8000   (backend/app/main.py)                 │
│                                                         │
│  POST /api/entries   ──► storage.py ──► pipeline.py     │
│  GET  /api/entries        (LocalStorageProvider)        │
│  GET  /api/timeline                                     │
│  GET  /api/search    ──► search.py (Qdrant)             │
│  GET  /api/entries/{id}/waveform ──► ml.py (librosa)    │
│  GET  /api/entries/{id}/similar  ──► search.py          │
└──────┬───────────────────────────┬──────────────────────┘
       │                           │
       ▼                           ▼
┌─────────────┐           ┌────────────────────┐
│  PostgreSQL │           │  Qdrant (local)    │
│  :5432      │           │  backend/          │
│  host:      │           │  qdrant_storage/   │
│  .201       │           │                    │
│             │           │  sonochron_text    │
│  Canonical  │           │  384-dim cosine    │
│  source of  │           │                    │
│  truth      │           │  sonochron_audio   │
│             │           │  1024-dim cosine   │
└─────────────┘           └────────────────────┘
```

---

## Request lifecycle — ingestion

```
Client POST /api/entries (multipart: file + metadata)
  │
  ├─ 1. Parse & validate local_capture_time
  ├─ 2. Idempotency check (IdempotencyKey table)
  ├─ 3. SHA-256 checksum + byte_size
  ├─ 4. Atomic Postgres transaction:
  │      YearArchive (get or create)
  │      MonthArchive (get or create)
  │      DiaryEntry  (stage = "uploaded")
  │      EntryContext (mood, location, companions, notes)
  │      SampleAsset  (filename, filepath, checksum, size)
  │      IdempotencyKey
  ├─ 5. Write raw audio → backend/storage/raw/{year}/{month}/{uuid}/{filename}
  ├─ 6. Return 201 JSON immediately
  └─ 7. asyncio.ensure_future → background thread → _run_pipeline()
```

---

## Processing pipeline

Each stage is stored on `DiaryEntry.stage` in Postgres. Stages are idempotent — the pipeline skips any stage the entry has already passed.

```
uploaded
  │
  ▼
validated ────── SampleAsset exists + byte_size > 0
  │
  ▼
speech_detected ─ Whisper tiny: preliminary transcript → EntryContext.notes
  │
  ▼
transcribed ───── Whisper tiny: full pass
  │               • Stores "[Transcript] …" in EntryContext.notes
  │               • Auto-fills DiaryEntry.title from first 10 words (if blank)
  │
  ▼
text_embedded ─── sentence-transformers all-MiniLM-L6-v2
  │               • Input: title + notes + mood + location + companions
  │               • Output: 384-dim L2-normalised vector (stashed on entry object)
  │
  ▼
audio_embedded —— CLAP (laion/larger_clap_general) neural audio embedding
  │               • GPU-accelerated via CUDA 11.8 (GTX 1050 Ti, sm_61)
  │               • Output: 512-dim L2-normalised vector
  │               • Falls back to librosa MFCC+mel stats on error
  │
  ▼
indexed ────────── Qdrant upsert (both collections, pre-computed vectors)
  │
  ▼
ready ─────────── Entry fully available for search + similarity
```

Any unhandled exception in a stage marks the entry `failed` and halts the pipeline. Qdrant errors are non-fatal (logged, entry still advances).

---

## ML models

All models are lazy-loaded singletons in [`backend/app/ml.py`](./backend/app/ml.py). They load on first use and are cached for the process lifetime.

| Model | Package | Dim | Purpose |
|---|---|---|---|
| Whisper tiny | `openai-whisper` | — | Speech detection + transcription |
| all-MiniLM-L6-v2 | `sentence-transformers` | 384 | Text semantic embeddings |
| CLAP (laion/larger_clap_general) | `msclap` | 512 | Neural audio understanding |
| MFCC + mel stats | `librosa` | 512 | Audio fingerprint (CLAP fallback) |
| RMS peaks | `librosa` | variable | Waveform UI data |

### GPU acceleration

CLAP runs on the GTX 1050 Ti via CUDA 11.8 (PyTorch `cu118` build, sm_61). GPU is
automatically detected via `torch.cuda.is_available()` at model load time.

To disable GPU and force CPU inference, set `USE_CLAP = False` or run without CUDA:
```python
# backend/app/ml.py
USE_CLAP = False  # forces librosa fallback
```

To rebuild the Qdrant index with CLAP embeddings:
```bash
python -m app.cli reindex
```

---

## Database schema

```
YearArchive (PK: year int)
  └─ MonthArchive (PK: uuid, FK: year, UNIQUE(year, month))
       └─ DiaryEntry (PK: uuid, FK: month_archive_id)
            │  fields: local_capture_time, utc_capture_time,
            │           title, stage, created_at, updated_at
            │
            ├─ EntryContext (PK: uuid, FK: entry_id UNIQUE)
            │    fields: mood, location, companions (JSON), notes
            │
            ├─ SampleAsset (PK: uuid, FK: entry_id UNIQUE)
            │    fields: filename, filepath, checksum_sha256,
            │             byte_size, duration_ms
            │
            └─ IdempotencyKey (PK: key str, FK: entry_id)
```

### Pipeline stages (DiaryEntry.stage)

`uploaded` → `validated` → `speech_detected` → `transcribed` → `text_embedded` → `audio_embedded` → `indexed` → `ready`

Failure: `failed`

---

## Storage layout

```
backend/storage/raw/
  {year}/
    {month:02d}/
      {entry_uuid}/
        {original_filename}      ← immutable, never overwritten
```

The `StorageProvider` ABC (`backend/app/storage.py`) abstracts all file I/O. `LocalStorageProvider` is the active implementation. `S3StorageProvider` (for SeaweedFS) is the planned replacement — the interface is ready, the implementation is not yet written.

---

## Vector search

Qdrant runs in local filesystem mode (no separate server process):

```
backend/qdrant_storage/   ← persistent Qdrant data directory
```

Two collections:

| Collection | Dim | Distance | Used for |
|---|---|---|---|
| `sonochron_text` | 384 | Cosine | Semantic text search (`GET /api/search?q=`) |
| `sonochron_audio` | 1024 | Cosine | Audio similarity (`GET /api/entries/{id}/similar`) |

The index is fully rebuildable from Postgres at any time:
```bash
python -m app.cli reindex
```

---

## Frontend

Single-page app (React 18 + TypeScript + Vite), served as a static production build.

| View | Purpose |
|---|---|
| **Capture** | Record audio (MediaRecorder API) or upload a file. Fill metadata fields. |
| **Timeline** | Browse entries grouped by year → month. Inline expansion with audio player + waveform. |
| **Search** | Debounced semantic text search. Similarity search from any entry. |

Design system: parchment background (`#F5F0E8`), charcoal ink (`#1C1A18`), amber accent (`#B8832A`), EB Garamond serif, IBM Plex Mono.

---

## Infrastructure

| Component | Technology |
|---|---|
| Host | Proxmox LXC (Debian) |
| Process manager | pm2 7 (`ecosystem.config.cjs`) |
| Startup | systemd `pm2-jackc.service` |
| Database | PostgreSQL 14 on `192.168.0.201:5432` |
| Vector DB | Qdrant local mode |
| Audio storage | Local filesystem (S3/SeaweedFS planned) |

---

## What's not yet built

| Item | Notes |
|---|---|
| `S3StorageProvider` | `StorageProvider` interface in `storage.py` is ready; implementation pending |
