#!/usr/bin/env bash
# pm2 entry point — wraps uvicorn so pm2 tracks a stable PID
set -euo pipefail
cd "$(dirname "$0")"
# Load all vars from .env (silently skip if missing)
set -a
source .env 2>/dev/null || true
set +a
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
