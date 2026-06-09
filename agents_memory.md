# Sonochron — Agent Memory
> Read on startup. Update on meaningful change. Lean, high-density, facts only.
> QDRANT WORK: Read `.agents/QDRANT_SKILLS.md` and use `https://skills.qdrant.tech/snippets/search?language=python&query=<topic>` for canonical SDK examples.

## Identity & Core Principle
Personal sound diary; capture-first, archival feel (not a sample manager).
Priority order: **capture → context → search**.

## Environment & Ports
* **Host/IP:** Proxmox LXC | `192.168.0.204` (UI: `:5173`, API: `:8000`)
* **PostgreSQL:** `192.168.0.201:5432` | db=`sonochron` | user=`postgres`
* **Qdrant:** Local filesystem (`backend/qdrant_storage/`), singleton client mode.
* **Storage:** Local filesystem (`backend/storage/raw/`) via `StorageProvider`. SeaweedFS S3 pending.

## Stack
* **Backend:** Python 3.12 · FastAPI · SQLModel/SQLAlchemy 2 (sync) · Uvicorn
* **Vector DB:** qdrant-client 1.18 (Local mode)
* **Frontend:** Vite 5 · React 18 · TypeScript (Plain CSS, no Tailwind)
* **Process Mgr:** pm2 7 (`ecosystem.config.cjs`) | systemd `pm2-jackc.service` for auto-reboot.

## Codebase, Schema & Pipeline
* **Paths:** Backend in `backend/`, Frontend in `frontend/`. Use `sigmap` for dynamic queries.
* **Schema:** `backend/app/database.py` (YearArchive → MonthArchive → DiaryEntry → Context/Asset/Idempotency).
* **Pipeline Stages:** `uploaded → validated → speech_detected → transcribed → text_embedded → audio_embedded → indexed → ready`
* **ML Engines (`ml.py`):** Lazy-loaded singletons. 
  * `speech_detected` / `transcribed`: Whisper tiny. Auto-fills titles; saves to `EntryContext.notes`.
  * `text_embedded`: `all-MiniLM-L6-v2` (384-dim cosine). Collection: `sonochron_text`.
  * `audio_embedded`: `laion/larger_clap_general` (1024-dim cosine). Collection: `sonochron_audio`.
  * *Fallback:* Librosa scales MFCC/mel to 1024-dim for schema consistency if GPU is lost.
* **Indexing:** `search.upsert_entry()` pushes pre-computed vectors to Qdrant.

## GPU / CUDA Status
* **Hardware:** GTX 1050 Ti (4GB VRAM) | Driver 580.159.04 | CUDA 13.0
* **Status:** GPU passthrough verified/working for PyTorch, Whisper, and CLAP.

## Google Drive & Media Ingestion
* **Engine:** `backend/app/drive.py` (OAuth2 tokens in `.google_tokens.json`; cache in `.drive_imported.json`).
* **Processing:** Background auto-sync every 30 mins or via `POST /api/drive/sync`.
* **ffmpeg:** Converts downloaded audio to 16-bit 44.1kHz mono WAV via subprocess before ingestion.

## Design System (Frontend UI)
* **Tokens:** `--bg: #F5F0E8` (parchment) | `--bg-entry: #EDE7D9` (cream) | `--ink: #1C1A18` (charcoal) | `--amber: #B8832A` | Font: `EB Garamond` (serif), `IBM Plex Mono` (mono).
* **Rules:** No glassmorphism. Max `border-radius: 2px`. No metadata chips/pills (use monospace `·` separators). Details use inline expansion. Recording dot pulses red.

## Deployment Commands
```bash
./deploy.sh [restart|logs|status]   # System controls
cd backend && export $(grep -v '^#' .env | xargs)
.venv/bin/python3 -m app.cli reindex               # Requires server stopped
.venv/bin/python3 -m app.cli check-entry <uuid>
