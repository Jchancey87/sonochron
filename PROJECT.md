# Project: Sonochron

## Architecture
Sonochron is a personal sound diary consisting of:
1. **Frontend**: Vite + React + TypeScript web client. Provides an intuitive capture UI (recording audio, capturing metadata like mood, location, companions, notes) and a timeline browser grouped by year/month archives.
2. **Backend**: FastAPI server. Serves API endpoints for ingestion (idempotency support) and timeline retrieval. Connects to PostgreSQL database as the canonical store.
3. **Database**: PostgreSQL (host `192.168.0.201:5432`, database `sonochron`). Stores YearArchive, MonthArchive, DiaryEntry, EntryContext, SampleAsset, and processing states.
4. **Storage Layer**: Abstracted file storage system. A unified interface for storing raw/processed audio assets, defaults to local filesystem directory storage, and is designed to transition to SeaweedFS S3.
5. **Processing Pipeline**: Background worker or task queue in FastAPI that updates diary entries through explicit processing stages (`uploaded`, `validated`, `speech_detected`, `transcribed`, `text_embedded`, `audio_embedded`, `indexed`, `failed`). Uses mock ML models (embeddings and transcripts).
6. **Vector Search Index**: Local Qdrant client/server. Indexes text semantic vectors (user notes, context, transcripts) and audio similarity vectors. Rebuildable from PostgreSQL state.

## Milestones
| # | Name | Scope | Dependencies | Status | Conv ID |
|---|------|-------|-------------|--------|---------|
| 1 | M1: DB & Storage Setup | Schema in PostgreSQL and abstracted storage layer interface/local impl. | None | DONE | d78e2f92-22b1-449a-9510-57c3c691f17e |
| 2 | M2: Backend API & Ingestion | FastAPI endpoints for timeline and file upload with idempotency. | M1 | DONE | be79fe44-762f-4416-bb5a-98eb452e0bce |
| 3 | M3: Ingest Processing Pipeline | Stage-based processing pipeline with mock ML embeddings/transcripts. | M2 | DONE | db4f5e5c-ec5b-48d3-8172-06352982fe44 |
| 4 | M4: Qdrant Search & CLI | Qdrant integration, text/audio similarity search, and rebuild CLI. | M3 | IN_PROGRESS | 9567ea6f-437a-4be9-9d6e-4d3d623e7c94 |
| 5 | M5: Frontend Timeline UI | Vite + React + TS capture tool and timeline interface. | M2 | PLANNED | TBD |
| 6 | M6: E2E Integration & Phase 2 | Phase 1 E2E tests verification, Phase 2 Adversarial coverage hardening. | M4, M5 | PLANNED | TBD |

## Interface Contracts
### Ingestion API
- `POST /api/entries`
  - Headers: `X-Idempotency-Key: <UUID>`
  - Body (Multipart):
    - `file`: Audio file binary (WAV, MP3, etc.)
    - `local_capture_time`: ISO8601 string (e.g., `2026-06-06T12:35:00Z`)
    - `mood`: String (optional)
    - `location`: String (optional)
    - `companions`: List of strings (optional, comma-separated or JSON list)
    - `notes`: String (optional)
  - Response: JSON object representing the newly created entry, including its current state.

### Timeline API
- `GET /api/timeline`
  - Response: Grouped hierarchy of YearArchive and MonthArchive.
- `GET /api/entries/{id}`
  - Response: DiaryEntry details, including EntryContext, SampleAsset, and current processing stage.

### Storage Interface
- `StorageProvider` (abstract base class / protocol):
  - `async def store_file(path_key: str, data: bytes) -> str`
  - `async def retrieve_file(path_key: str) -> bytes`
  - `async def delete_file(path_key: str) -> None`

### Search API
- `GET /api/search`
  - Query parameters:
    - `q`: Text search query (semantic)
    - `similarity_entry_id`: Entry ID for audio similarity search (optional)
  - Response: List of matching DiaryEntry records with scores.

### Index Rebuild CLI
- A CLI tool or script to purge and completely rebuild the Qdrant vector index from PostgreSQL database state.
- Command syntax: `python -m app.cli rebuild-index` or similar.

## Code Layout
- `backend/`: FastAPI application directory
  - `app/`
    - `database.py` (SQLAlchemy/SQLModel models, session config)
    - `storage.py` (Storage interface and local filesystem impl)
    - `pipeline.py` (Mock ML stages and ingestion worker)
    - `search.py` (Qdrant client and indexing)
    - `main.py` (FastAPI application and endpoints)
    - `cli.py` (CLI tools including index rebuild)
- `frontend/`: Vite + React + TypeScript application directory
- `tests/`: End-to-end and integration test suite (managed by E2E Testing Track)
