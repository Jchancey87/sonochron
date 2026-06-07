# Sonochron — Agent Memory
> Read this at the start of every session. Update when something meaningful changes.
> Keep it lean. Facts only. No prose padding.

> **IMPORTANT — Qdrant Work:** Before touching any Qdrant code, read
> `.agents/QDRANT_SKILLS.md` first. Official skill files are in
> `.agents/skills/qdrant/`. Use `https://skills.qdrant.tech/snippets/search?language=python&query=<topic>`
> for canonical SDK code examples.

---

## Identity
Personal sound diary. Capture-first, archival feel. Not a sample manager.
Core principle: **capture → context → search**, in that priority order.

---

## Environment
| | |
|---|---|
| Host | Proxmox LXC container |
| IP | `192.168.0.204` |
| User | `jackc` (sudo password: `<redacted/stored locally>`) |
| PostgreSQL | `192.168.0.201:5432` db=`sonochron` user=`postgres` pass=`<stored in backend/.env>` |
| Qdrant | Local filesystem — `backend/qdrant_storage/` (singleton client, no server process) |
| Storage | Local filesystem — `backend/storage/raw/` (abstracted via `StorageProvider`) |
| Object store | SeaweedFS planned — `S3StorageProvider` not yet implemented |

---

## Stack
| Layer | Tech |
|---|---|
| Backend | Python 3.12 · FastAPI · SQLModel · Uvicorn |
| Database ORM | SQLModel / SQLAlchemy 2 (sync) |
| Vector DB | qdrant-client 1.18 local mode |
| Frontend | Vite 5 · React 18 · TypeScript (no Tailwind) |
| Process mgr | pm2 7 — `ecosystem.config.cjs` |
| Startup | systemd `pm2-jackc.service` (auto-resurrect on reboot) |

---

## Codebase & Schema (sigmap integrated)
- **Project Structure**: Standard Python backend in [backend/](file:///home/jackc/projects/sonochron/backend) and React/TS frontend in [frontend/](file:///home/jackc/projects/sonochron/frontend). Use `sigmap` tools for dynamic file structure and code signature queries.
- **Database Schema**: PostgreSQL. Models (YearArchive → MonthArchive → DiaryEntry → Context/Asset/Idempotency) defined in [database.py](file:///home/jackc/projects/sonochron/backend/app/database.py).
- **API Endpoints**: FastAPI endpoints defined in [main.py](file:///home/jackc/projects/sonochron/backend/app/main.py). Frontend API calls mapped in [api.ts](file:///home/jackc/projects/sonochron/frontend/src/api.ts).

---

## Pipeline Stages
`uploaded → validated → speech_detected → transcribed → text_embedded → audio_embedded → indexed → ready`

- **All ML stages are real** (session 5). Models in [ml.py](file:///home/jackc/projects/sonochron/backend/app/ml.py):
  - `speech_detected`: Whisper tiny detects speech, stores preliminary transcript.
  - `transcribed`: Whisper tiny — full pass, stores `[Transcript] …` in EntryContext.notes, auto-fills title if blank.
  - `text_embedded`: sentence-transformers `all-MiniLM-L6-v2` — real 384-dim cosine embeddings.
  - `audio_embedded`: laion/larger_clap_general (falls back to scaled MFCC/mel if GPU is unavailable) — real 1024-dim cosine embeddings.
- All models are lazy-loaded singletons (first use only, thread-safe).
- `indexed` stage calls `search.upsert_entry()` with pre-computed vectors — writes to Qdrant.
- Qdrant collections: `sonochron_text` (384-dim cosine) · `sonochron_audio` (1024-dim cosine). Singleton client configured in [search.py](file:///home/jackc/projects/sonochron/backend/app/search.py).

---

## Design System (Frontend)
| Token | Value |
|---|---|
| `--bg` | `#F5F0E8` parchment |
| `--bg-entry` | `#EDE7D9` cream row tint |
| `--ink` | `#1C1A18` charcoal |
| `--ink-muted` | `#6B6560` |
| `--ink-faint` | `#A8A29C` |
| `--amber` | `#B8832A` accent |
| `--serif` | EB Garamond |
| `--mono` | IBM Plex Mono |

**Rules:** No glassmorphism. No border-radius >2px. No chips/pills for metadata.
Metadata: plain monospace `mood · location · notes…` with `·` separators.
Entry detail: inline expansion (no new page). Record dot pulses red only while recording.

---

## Deployment
```bash
# Full rebuild + deploy
./deploy.sh

# Daily ops
./deploy.sh restart   # after code changes
./deploy.sh logs      # tail live logs
./deploy.sh status    # pm2 process table

# CLI tools (server must be stopped for reindex)
cd backend
export $(grep -v '^#' .env | xargs)
.venv/bin/python3 -m app.cli reindex
.venv/bin/python3 -m app.cli check-entry <uuid>
```

Ports: **API :8000** · **UI :5173**  
pm2 auto-resurrects via `/etc/systemd/system/pm2-jackc.service` on reboot.

---

## Google Drive Integration
| File | Purpose |
|---|---|
| `backend/app/drive.py` | OAuth2, file listing, download, ffmpeg conversion, import |
| `backend/.google_tokens.json` | Persisted OAuth2 tokens (gitignored) |
| `backend/.drive_imported.json` | Tracks already-imported Drive file IDs (gitignored) |

**Env vars required:**
```
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=https://sonochron.homma.casa/api/drive/callback  # or override
GOOGLE_DRIVE_FOLDER=<folder-id-or-URL>  # optional; defaults to all audio files
```

**ffmpeg usage:** Downloaded audio files are converted to 16-bit 44.1kHz mono WAV via ffmpeg subprocess before ingestion.

**Auto-sync:** Runs every 30 min in background (FastAPI startup task). Manual trigger: `POST /api/drive/sync`.

---

## Not Yet Built
- [ ] `S3StorageProvider` for SeaweedFS (`storage.py` interface is ready)
- [x] Real audio embeddings (CLAP) — verified and working (session 5)
- [x] Real text embeddings (sentence-transformers `all-MiniLM-L6-v2`)
- [x] Real audio transcription (Whisper tiny)
- [x] Real waveform data (librosa RMS peaks via `/api/entries/{id}/waveform`)
- [x] `PATCH /api/entries/{id}` — partial update + Qdrant re-index
- [x] `DELETE /api/entries/{id}` — cascade DB + storage + Qdrant
- [x] CORS locked to `http://192.168.0.204:5173`

---

## GPU / CUDA Status (session 5)

**GPU:** NVIDIA GeForce GTX 1050 Ti with Max-Q Design · 4 GB VRAM · Driver 580.159.04 · CUDA 13.0  
**Status:** **GPU PASSTHROUGH VERIFIED AND WORKING**. CUDA is fully available to PyTorch and detects the GTX 1050 Ti.
- Verified that the pipeline verification integration test runs successfully using real Whisper (tiny) and CLAP (laion/larger_clap_general) models.
- Updated `tests/verify_real_pipeline.py` to expect 1024-dimensional embeddings (matching the CLAP 2023 version schema in Qdrant) and fixed its import/select error.
- Updated the fallback librosa implementation in `backend/app/ml.py` to output 1024-dim embeddings (instead of the old 512-dim) by scaling MFCC and mel coefficients to 256 each, ensuring schema consistency across both primary and fallback code paths.

---

## Qdrant Skills
| Resource | Path |
|---|---|
| Skills guide (Sonochron-specific) | `.agents/QDRANT_SKILLS.md` |
| All skill files | `.agents/skills/qdrant/` |
| Upstream source | https://github.com/qdrant/skills |
| Code snippet API | `https://skills.qdrant.tech/snippets/search?language=python&query=<topic>` |

Key skills for Sonochron: **model-migration** (for CLAP/PANNs swap), **search-quality** (hybrid search future work), **clients-sdk** (Python API examples).

---

*Last updated: 2026-06-07 (session 6 — Google Drive integration + ffmpeg; test suite fixed: 49/49 passing)*
