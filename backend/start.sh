#!/bin/bash
set -e
cd "$(dirname "$0")"
source .venv/bin/activate
export $(grep -v '^#' .env | xargs)
export DATABASE_URL="postgresql://${DB_USER}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
