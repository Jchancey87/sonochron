# Sonochron

A personal sound diary. Capture audio moments, add context (mood, location, companions, notes), and rediscover them later through semantic search and audio similarity.

**Core philosophy:** capture → context → search.

---

## Quick Start

### Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.12+ |
| Node.js | 18+ |
| PostgreSQL | 14+ (remote at `192.168.0.201`) |
| pm2 | 7+ (`npm i -g pm2`) |

### First-time setup

```bash
# 1. Clone / enter the project
cd /home/jackc/projects/sonochron

# 2. Create Python venv and install backend deps
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd ..

# 3. Install frontend deps and build
cd frontend
npm install
npm run build
cd ..

# 4. Configure environment
cp backend/.env.example backend/.env   # edit DB creds if needed

# 5. Deploy (starts both API + UI via pm2)
./deploy.sh
```

### Daily operations

```bash
./deploy.sh           # full build + deploy
./deploy.sh restart   # restart after code changes (no build)
./deploy.sh stop      # stop all processes
./deploy.sh logs      # tail live logs
./deploy.sh status    # pm2 process table
```

---

## Services

| Service | Port | Process name |
|---|---|---|
| FastAPI backend | `:8000` | `sonochron-api` |
| React frontend | `:5173` | `sonochron-ui` |

Frontend is served as a production build via `serve`. API docs available at `http://192.168.0.204:8000/docs`.

---

## Environment variables

Backend reads from `backend/.env`:

```env
DB_HOST=192.168.0.201
DB_PORT=5432
DB_NAME=sonochron
DB_USER=postgres
DB_PASS=<password>
```

Frontend reads from `frontend/.env`:

```env
VITE_API_URL=http://192.168.0.204:8000
```

---

## API reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/entries` | Upload audio + metadata. Multipart. Header: `X-Idempotency-Key` |
| `GET` | `/api/entries` | List entries. Query: `?year=&month=&limit=&offset=` |
| `GET` | `/api/entries/{id}` | Single entry with context + asset |
| `PATCH` | `/api/entries/{id}` | Update title, mood, location, companions, notes |
| `DELETE` | `/api/entries/{id}` | Delete entry + audio + Qdrant vectors |
| `GET` | `/api/entries/{id}/audio` | Stream raw audio |
| `GET` | `/api/entries/{id}/waveform` | Real waveform peaks. Query: `?bars=100` |
| `GET` | `/api/entries/{id}/similar` | Audio similarity search |
| `GET` | `/api/timeline` | Year/month archive hierarchy |
| `GET` | `/api/search` | Semantic text search. Query: `?q=&year=&month=&mood=&limit=` |
| `GET` | `/health` | `{"status":"ok"}` |

---

## CLI tools

Run these from the `backend/` directory with the server stopped:

```bash
# Rebuild entire Qdrant vector index from Postgres
DB_HOST=192.168.0.201 DB_USER=postgres DB_PASS="..." DB_NAME=sonochron \
  .venv/bin/python3 -m app.cli reindex

# Inspect a single entry's pipeline state
.venv/bin/python3 -m app.cli check-entry <uuid>
```

---

## Startup on reboot

pm2 is registered as a systemd service:

```bash
sudo systemctl enable pm2-jackc   # already done
sudo systemctl start pm2-jackc    # resurrects all pm2 processes
```

---

## Project layout

```
sonochron/
├── backend/
│   ├── app/
│   │   ├── main.py        # FastAPI app + all endpoints
│   │   ├── database.py    # SQLModel models + session helpers
│   │   ├── storage.py     # StorageProvider ABC + LocalStorageProvider
│   │   ├── pipeline.py    # Stage-based background processing pipeline
│   │   ├── ml.py          # ML model singletons (Whisper, sentence-transformers, librosa)
│   │   ├── search.py      # Qdrant client + text/audio search
│   │   └── cli.py         # python -m app.cli reindex | check-entry <id>
│   ├── .venv/
│   ├── .env               # DB creds (not committed)
│   ├── requirements.txt
│   └── storage/raw/       # Local audio file storage
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── api.ts
│   │   ├── views/         # CaptureView, TimelineView, SearchView
│   │   └── components/    # EntryRow, Waveform
│   └── dist/              # Production build
├── systemd/               # systemd unit files (alternative to pm2)
├── logs/                  # pm2 log output
├── ecosystem.config.cjs   # pm2 process definitions
├── deploy.sh              # Deployment script
├── agents_memory.md       # Agent session memory (do not delete)
├── README.md              # ← this file
└── ARCHITECTURE.md        # System design reference
```

---

## See also

- [ARCHITECTURE.md](./ARCHITECTURE.md) — component diagram, data flow, pipeline stages, extension points
- [agents_memory.md](./agents_memory.md) — session-to-session agent context (implementation details, decisions)
