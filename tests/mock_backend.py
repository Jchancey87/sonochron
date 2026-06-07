"""
mock_backend.py — Sonochron test mock backend.

Uses an in-memory database (protected by a threading.Lock) so concurrent
pipeline threads and HTTP handlers never race on JSON file I/O.
"""
import os
import re
import uuid
import time
import copy
import json
import threading
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse

app = FastAPI(title="Sonochron Mock Backend")

# ---------------------------------------------------------------------------
# In-memory DB — all mutations are lock-protected
# ---------------------------------------------------------------------------
_db_lock = threading.Lock()
_db: Dict[str, Any] = {"entries": {}, "idempotency_keys": {}}
_db_file_mtime: float = 0.0  # mtime of last file we wrote; used to detect subprocess writes

# Also keep a JSON file for the mock_cli subprocess (different process)
DB_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "mock_db.json"))

def _flush_to_file():
    """Snapshot the in-memory DB under lock, then write to JSON outside lock.
    This prevents the 'dictionary changed size during iteration' error in json.dump.
    """
    global _db_file_mtime
    with _db_lock:
        snapshot = copy.deepcopy(_db)
    with open(DB_FILE, "w") as f:
        json.dump(snapshot, f, indent=2)
    try:
        _db_file_mtime = os.path.getmtime(DB_FILE)
    except Exception:
        pass

def _maybe_reload_from_file():
    """If the JSON file has been updated by an external process (e.g. mock_cli subprocess),
    reload the in-memory DB so subsequent reads reflect those changes.
    Must be called while holding _db_lock.
    """
    global _db, _db_file_mtime
    try:
        mtime = os.path.getmtime(DB_FILE)
    except Exception:
        return
    if mtime > _db_file_mtime + 0.01:  # 10ms tolerance
        try:
            with open(DB_FILE, "r") as f:
                _db = json.load(f)
            _db_file_mtime = mtime
        except Exception:
            pass

def load_db() -> dict:
    """Return a deep copy of the current in-memory DB, reloading from file if needed."""
    with _db_lock:
        _maybe_reload_from_file()
        return copy.deepcopy(_db)

def save_db(db: dict):
    """Replace the in-memory DB with db and flush to file."""
    global _db
    with _db_lock:
        _db = copy.deepcopy(db)
    _flush_to_file()

def _update_entry_stage_locked(entry_id: str, stage: str, run_token: Optional[str]) -> bool:
    """Atomically update an entry's stage.  Must be called while holding _db_lock.
    If run_token is provided the update is rejected when the stored token doesn't match.
    Returns True if the update was applied.
    """
    entry = _db["entries"].get(entry_id)
    if entry is None:
        return False
    if run_token is not None and entry.get("_pipeline_token") != run_token:
        return False
    entry["stage"] = stage
    return True

def update_entry_stage(entry_id: str, stage: str, run_token: Optional[str] = None) -> bool:
    """Public helper (also used by tests directly).
    When called without run_token (e.g., by a test to simulate corruption),
    clears the pipeline token so any running pipeline thread stops.
    """
    with _db_lock:
        # Check for external file changes first
        _maybe_reload_from_file()
        applied = _update_entry_stage_locked(entry_id, stage, run_token)
        if applied and run_token is None:
            # External override — invalidate any running pipeline token
            entry = _db["entries"].get(entry_id)
            if entry is not None:
                entry["_pipeline_token"] = None
    if applied:
        _flush_to_file()
    return applied

# ---------------------------------------------------------------------------
# Background pipeline
# ---------------------------------------------------------------------------
PIPELINE_STAGES = [
    "uploaded",
    "validated",
    "speech_detected",
    "transcribed",
    "text_embedded",
    "audio_embedded",
    "indexed",
    "ready",
]

def _pipeline_thread(entry_id: str, notes: Optional[str], run_token: str):
    """Run the pipeline asynchronously in a daemon thread.

    Using a daemon thread (not BackgroundTasks) means the HTTP response is
    returned before the pipeline starts, so the entry is visible as "uploaded"
    right after POST.  Each stage takes ~1 ms so 20 concurrent pipelines all
    finish within ~16 ms, well inside the 100-150 ms test timeouts.
    """
    for stage in PIPELINE_STAGES:
        time.sleep(0.001)

        if stage == "validated" and notes and "fail" in notes.lower():
            update_entry_stage(entry_id, "failed", run_token)
            return

        if not update_entry_stage(entry_id, stage, run_token):
            return  # token mismatch — external override (CLI reindex etc.)

def start_pipeline(entry_id: str, notes: Optional[str], run_token: str):
    t = threading.Thread(
        target=_pipeline_thread, args=(entry_id, notes, run_token), daemon=True
    )
    t.start()

# ---------------------------------------------------------------------------
# Search helpers
# ---------------------------------------------------------------------------
def _tokenize(text: str) -> set:
    return set(re.sub(r"[^\w\s]", "", text.lower()).split())

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.post("/api/entries")
async def create_entry(
    file: UploadFile = File(...),
    local_capture_time: str = Form(...),
    mood: str = Form(""),
    location: str = Form(""),
    companions: str = Form(""),
    notes: str = Form(""),
    x_idempotency_key: Optional[str] = Header(None),
):
    # Use None for truly absent (empty) fields only when blank
    # Empty string stays as empty string — matching test expectations.
    def _norm(v: str) -> Optional[str]:
        # We keep empty string as-is; caller decides None vs "".
        return v  # never coerce "" → None

    mood_val: Optional[str] = mood if mood != "" else ""
    location_val: Optional[str] = location if location != "" else ""
    notes_val: Optional[str] = notes if notes != "" else ""
    companions_raw: Optional[str] = companions if companions != "" else None


    # Parse companions
    companions_list: List[str] = []
    if companions_raw:
        try:
            parsed = json.loads(companions_raw)
            companions_list = parsed if isinstance(parsed, list) else [companions_raw]
        except Exception:
            companions_list = [c.strip() for c in companions_raw.split(",") if c.strip()]

    with _db_lock:
        # Idempotency check (atomic)
        if x_idempotency_key and x_idempotency_key in _db["idempotency_keys"]:
            existing_id = _db["idempotency_keys"][x_idempotency_key]
            if existing_id in _db["entries"]:
                return copy.deepcopy(_db["entries"][existing_id])

        entry_id = str(uuid.uuid4())
        run_token = str(uuid.uuid4())

        # Save audio file
        storage_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "storage"))
        os.makedirs(storage_dir, exist_ok=True)
        safe_filename = f"{entry_id}_{file.filename}"
        file_path = os.path.join(storage_dir, safe_filename)

        content = b""  # read outside lock is fine since we already have the upload

    # Read file outside the lock (no DB mutation here)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="Empty file uploaded")
    with open(file_path, "wb") as fh:
        fh.write(content)

    entry = {
        "id": entry_id,
        "local_capture_time": local_capture_time,
        "stage": "uploaded",
        "_pipeline_token": run_token,
        "context": {
            "mood": mood_val,
            "location": location_val,
            "companions": companions_list,
            "notes": notes_val,
        },
        "asset": {
            "filename": file.filename,
            "filepath": file_path,
        },
    }

    with _db_lock:
        _db["entries"][entry_id] = entry
        if x_idempotency_key:
            _db["idempotency_keys"][x_idempotency_key] = entry_id

    _flush_to_file()

    # Launch pipeline AFTER the entry is committed
    start_pipeline(entry_id, notes_val, run_token)

    return copy.deepcopy(entry)

@app.get("/api/timeline")
async def get_timeline():
    with _db_lock:
        _maybe_reload_from_file()
        entries = list(copy.deepcopy(_db["entries"]).values())

    grouped: Dict[int, Dict[int, list]] = {}
    for entry in entries:
        time_str = entry.get("local_capture_time") or ""
        try:
            year = int(time_str[:4])
            month = int(time_str[5:7])
        except Exception:
            year, month = 2026, 6
        grouped.setdefault(year, {}).setdefault(month, []).append(entry)

    result = []
    for y in sorted(grouped.keys(), reverse=True):
        months_list = []
        for m in sorted(grouped[y].keys(), reverse=True):
            sorted_entries = sorted(
                grouped[y][m],
                key=lambda x: x.get("local_capture_time", ""),
                reverse=True,
            )
            months_list.append({"month": m, "entries": sorted_entries})
        result.append({"year": y, "months": months_list})
    return result

@app.get("/api/entries/{id}")
async def get_entry_details(id: str):
    with _db_lock:
        _maybe_reload_from_file()
        entry = _db["entries"].get(id)
        if entry is None:
            raise HTTPException(status_code=404, detail="Entry not found")
        return copy.deepcopy(entry)

@app.get("/api/search")
async def search_entries(
    q: Optional[str] = None,
    similarity_entry_id: Optional[str] = None,
):
    if not q and not similarity_entry_id:
        return []

    with _db_lock:
        _maybe_reload_from_file()
        entries = list(copy.deepcopy(_db["entries"]).values())

    results = []
    for entry in entries:
        if entry.get("stage") == "failed":
            continue

        score = 0.0

        if q:
            q_words = _tokenize(q)
            ctx = entry.get("context", {})
            combined = " ".join([
                ctx.get("notes") or "",
                ctx.get("mood") or "",
                ctx.get("location") or "",
                " ".join(ctx.get("companions") or []),
            ])
            content_words = _tokenize(combined)
            if q_words:
                score = len(q_words & content_words) / len(q_words)

        if similarity_entry_id:
            with _db_lock:
                ref = copy.deepcopy(_db["entries"].get(similarity_entry_id))
            if ref:
                if entry["id"] == similarity_entry_id:
                    score = max(score, 1.0)
                else:
                    ref_mood = (ref.get("context", {}).get("mood") or "").lower()
                    cur_mood = (entry.get("context", {}).get("mood") or "").lower()
                    mood_match = 0.5 if ref_mood and ref_mood == cur_mood else 0.0
                    ref_comps = set(ref.get("context", {}).get("companions") or [])
                    cur_comps = set(entry.get("context", {}).get("companions") or [])
                    comp_match = (
                        len(ref_comps & cur_comps) / len(ref_comps | cur_comps) * 0.5
                        if ref_comps and cur_comps else 0.0
                    )
                    score = max(score, mood_match + comp_match)

        if score > 0.0:
            results.append({**entry, "score": round(score, 4)})

    results.sort(key=lambda x: x["score"], reverse=True)
    return results

@app.post("/api/admin/reset")
async def reset_db():
    global _db
    with _db_lock:
        _db = {"entries": {}, "idempotency_keys": {}}
    _flush_to_file()
    storage_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "storage"))
    if os.path.exists(storage_dir):
        for f in os.listdir(storage_dir):
            try:
                os.remove(os.path.join(storage_dir, f))
            except Exception:
                pass
    return {"status": "reset"}
