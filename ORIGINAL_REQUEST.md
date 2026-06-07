# Original User Request

## Initial Request — 2026-06-06T12:34:45Z

Sonochron is a personal sound diary for capturing field recordings, sketches, textures, voice notes, and moments as part of a lived timeline, emphasizing low-friction capturing, rich contextual metadata, and search (semantic/similarity) as an enhancement layer.

Working directory: `/home/jackc/projects/sonochron`
Integrity mode: development

## Requirements

### R1. Low-Friction Audio Capture & Timeline UI
A Vite + React (TypeScript) frontend designed for fast, reliable browser-based audio capture (handling permissions, states, format constraints) and an intimate timeline browser (grouped by local-time months/years, supporting mood, location, and companion metadata).

### R2. FastAPI Backend & Canonical PostgreSQL Store
A FastAPI backend serving as the primary API. It must connect to the PostgreSQL instance at `192.168.0.201:5432` (creating/using a new database `sonochron`). PostgreSQL serves as the canonical source of truth for archives, entries, sample metadata, and stage-based processing states.

### R3. Local Qdrant Vector Search Indexing
An indexing pipeline worker that uses local filesystem storage via the Qdrant client (or local server) for text semantic vectors (user notes, context, transcripts) and audio similarity vectors. The Qdrant index must be fully derived and rebuildable from the database state.

### R4. Abstracted Storage Provider (Local / SeaweedFS S3)
An immutable storage layer using a local directory for files, structured using a storage provider interface (abstraction) that allows seamless transition to self-hosted SeaweedFS S3-compatible storage in the future.

## Acceptance Criteria

### Chronological timeline and browsing
- [ ] Timeline interface allows browsing entries grouped by local year and month archives.
- [ ] Individual entry pages display metadata (mood, weather, location, companions, etc.) and a functional audio player.

### Capture and Ingestion
- [ ] Web-based audio capture tool records audio and submits it to the backend.
- [ ] API accepts audio file plus metadata payload (including local capture time) with idempotency keys to prevent duplicate creation.
- [ ] API transaction inserts records in Postgres across YearArchive, MonthArchive, DiaryEntry, EntryContext, and SampleAsset, then enqueues analysis.

### Processing Pipeline (Mocked ML)
- [ ] Ingestion updates explicit, inspectable stages (uploaded, validated, speech_detected, transcribed, text_embedded, audio_embedded, indexed, failed) in PostgreSQL.
- [ ] Audio and text embeddings are generated using mock models (e.g. dummy vectors/transcripts) to verify the pipeline end-to-end.
- [ ] Verification script shows that database state matches processing stage transitions.

### Search and Rebuildability
- [ ] Text semantic search and audio similarity search return correct entry references.
- [ ] A script or CLI command can rebuild the Qdrant index entirely from Postgres state.
