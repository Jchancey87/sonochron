"""
drive.py — Google Drive integration for Sonochron.

Handles OAuth2 authentication, listing audio files from a configured
Drive folder, downloading them, converting to 16-bit 44.1kHz mono WAV
via ffmpeg, and feeding them into the existing ingestion pipeline.

Token storage: backend/.google_tokens.json  (gitignored)
Import log:    backend/.drive_imported.json  (gitignored)
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger("sonochron.drive")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_BACKEND_DIR = Path(__file__).parent.parent          # backend/
TOKENS_FILE   = _BACKEND_DIR / ".google_tokens.json"
IMPORTED_FILE = _BACKEND_DIR / ".drive_imported.json"

# ---------------------------------------------------------------------------
# OAuth2 config
# ---------------------------------------------------------------------------

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

REDIRECT_URI = os.environ.get(
    "GOOGLE_REDIRECT_URI",
    "https://sonochron.homma.casa/api/drive/callback",
)

AUDIO_MIMETYPES = [
    "audio/x-m4a", "audio/mp4", "audio/mpeg", "audio/wav",
    "audio/x-wav", "audio/ogg", "audio/aiff", "audio/x-aiff",
    "audio/flac", "audio/webm", "audio/3gpp",
]


def _client_config() -> dict:
    return {
        "web": {
            "client_id":     os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "redirect_uris": [REDIRECT_URI],
            "auth_uri":  "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def get_folder_id() -> Optional[str]:
    """Extract folder ID from GOOGLE_DRIVE_FOLDER env var (URL or plain ID)."""
    raw = os.environ.get("GOOGLE_DRIVE_FOLDER", "").strip()
    if not raw:
        return None
    # Handle full Google Drive URL: .../folders/{ID}?...
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", raw)
    if m:
        return m.group(1)
    # Assume it's already a plain folder ID
    return raw or None


# ---------------------------------------------------------------------------
# OAuth2 flow
# ---------------------------------------------------------------------------

def get_auth_url() -> str:
    """Return the Google OAuth2 consent URL."""
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES)
    flow.redirect_uri = REDIRECT_URI
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    return auth_url


def exchange_code(code: str) -> None:
    """Exchange an auth code for tokens and persist them."""
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES)
    flow.redirect_uri = REDIRECT_URI
    flow.fetch_token(code=code)
    creds = flow.credentials
    _save_tokens({
        "token":         creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri":     creds.token_uri,
        "client_id":     creds.client_id,
        "client_secret": creds.client_secret,
        "scopes":        list(creds.scopes or SCOPES),
    })
    logger.info("Google Drive OAuth2 tokens saved.")


def _save_tokens(data: dict) -> None:
    TOKENS_FILE.write_text(json.dumps(data, indent=2))


def get_credentials():
    """Load stored credentials, refreshing if expired. Returns None if not authed."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    if not TOKENS_FILE.exists():
        return None
    try:
        data = json.loads(TOKENS_FILE.read_text())
    except Exception:
        return None

    creds = Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes", SCOPES),
    )
    if not creds.valid and creds.refresh_token:
        try:
            creds.refresh(Request())
            data["token"] = creds.token
            _save_tokens(data)
        except Exception as exc:
            logger.warning("Failed to refresh Google token: %s", exc)
            return None
    return creds if creds.valid else None


def is_authenticated() -> bool:
    return get_credentials() is not None


def revoke() -> None:
    """Revoke and delete stored tokens."""
    if TOKENS_FILE.exists():
        TOKENS_FILE.unlink()
    logger.info("Google Drive credentials revoked.")


# ---------------------------------------------------------------------------
# Drive file listing
# ---------------------------------------------------------------------------

def list_audio_files() -> List[Dict]:
    """Return audio files from the configured Drive folder (or all of Drive)."""
    from googleapiclient.discovery import build

    creds = get_credentials()
    if not creds:
        raise PermissionError("Not authenticated with Google Drive.")

    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    folder_id = get_folder_id()

    mime_q = " or ".join(f"mimeType='{m}'" for m in AUDIO_MIMETYPES)

    if folder_id:
        query = f"({mime_q}) and '{folder_id}' in parents and trashed=false"
    else:
        query = f"({mime_q}) and trashed=false"

    results = service.files().list(
        q=query,
        fields="files(id,name,size,createdTime,modifiedTime,mimeType)",
        orderBy="createdTime desc",
        pageSize=200,
    ).execute()

    imported = get_imported_ids()
    files = results.get("files", [])
    for f in files:
        f["already_imported"] = f["id"] in imported
    return files


# ---------------------------------------------------------------------------
# Import tracking
# ---------------------------------------------------------------------------

def _load_import_log() -> dict:
    if not IMPORTED_FILE.exists():
        return {"ids": [], "entries": {}}
    try:
        return json.loads(IMPORTED_FILE.read_text())
    except Exception:
        return {"ids": [], "entries": {}}


def get_imported_ids() -> Set[str]:
    return set(_load_import_log().get("ids", []))


def mark_imported(drive_file_id: str, entry_id: str) -> None:
    log = _load_import_log()
    if drive_file_id not in log["ids"]:
        log["ids"].append(drive_file_id)
    log["entries"][drive_file_id] = str(entry_id)
    IMPORTED_FILE.write_text(json.dumps(log, indent=2))


# ---------------------------------------------------------------------------
# Download + convert
# ---------------------------------------------------------------------------

def download_and_convert(drive_file_id: str, filename: str) -> str:
    """
    Download a Drive file and convert to 16-bit 44.1kHz mono WAV.

    Returns the path to a temporary WAV file. Caller is responsible
    for deleting it after ingestion.
    """
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload

    creds = get_credentials()
    if not creds:
        raise PermissionError("Not authenticated with Google Drive.")

    service = build("drive", "v3", credentials=creds, cache_discovery=False)

    # Determine input suffix
    suffix = Path(filename).suffix.lower() or ".m4a"
    tmp_in  = tempfile.NamedTemporaryFile(suffix=suffix,    delete=False)
    tmp_out = tempfile.NamedTemporaryFile(suffix=".wav",    delete=False)
    tmp_in.close()
    tmp_out.close()

    try:
        # --- Download ---
        logger.info("Downloading Drive file %s (%s)", drive_file_id, filename)
        request = service.files().get_media(fileId=drive_file_id)
        with open(tmp_in.name, "wb") as fh:
            dl = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = dl.next_chunk()
        logger.info("Download complete: %s", tmp_in.name)

        # --- Convert with ffmpeg ---
        logger.info("Converting to 16-bit 44.1kHz mono WAV")
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", tmp_in.name,
                "-ar", "44100",       # 44.1 kHz sample rate
                "-ac", "1",           # mono
                "-sample_fmt", "s16", # 16-bit signed PCM
                tmp_out.name,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg conversion failed for {filename}:\n{result.stderr[-500:]}"
            )
        logger.info("Conversion complete: %s", tmp_out.name)
        return tmp_out.name

    finally:
        Path(tmp_in.name).unlink(missing_ok=True)


