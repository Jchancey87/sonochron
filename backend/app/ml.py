"""
ml.py — Real ML model wrappers for Sonochron.

Provides lazy-loaded singletons for:
  - Whisper (tiny) for audio transcription
  - sentence-transformers (all-MiniLM-L6-v2) for text embeddings
  - CLAP (laion/larger_clap_general via msclap) for audio embeddings

All models are loaded on first use and cached. This avoids loading
all models at startup (which would spike RAM and slow boot).

Audio embeddings use CLAP (1024-dim) with automatic GPU acceleration
when available. Falls back to librosa MFCC+mel statistics if CLAP
fails to load or errors on a particular file.
"""

from __future__ import annotations

import logging
import math
import re
import threading
from pathlib import Path
from typing import List, Optional

import numpy as np

logger = logging.getLogger("sonochron.ml")

# ---------------------------------------------------------------------------
# Thread-safe singleton locks
# ---------------------------------------------------------------------------

_whisper_lock = threading.Lock()
_st_lock = threading.Lock()
_clap_lock = threading.Lock()

_whisper_model = None
_st_model = None
_clap_model = None

# Set to False to force librosa fallback (useful for testing without GPU)
USE_CLAP = True

# ---------------------------------------------------------------------------
# Whisper — transcription
# ---------------------------------------------------------------------------

TEXT_EMBED_DIM = 384
AUDIO_EMBED_DIM = 1024  # matches CLAP larger_clap_general output dim

WHISPER_MODEL_SIZE = "tiny"  # swap to "base" or "small" with more RAM

# CLAP model version — "2023" uses laion/larger_clap_general (1024-dim)
CLAP_VERSION = "2023"


def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        with _whisper_lock:
            if _whisper_model is None:
                logger.info("Loading Whisper model: %s", WHISPER_MODEL_SIZE)
                import whisper
                _whisper_model = whisper.load_model(WHISPER_MODEL_SIZE)
                logger.info("Whisper model loaded.")
    return _whisper_model


def transcribe_audio(filepath: str) -> str:
    """
    Transcribe an audio file using Whisper tiny.

    Args:
        filepath: Absolute or relative path to audio file on disk.

    Returns:
        Transcribed text string (may be empty if no speech detected).
    """
    if not Path(filepath).exists():
        logger.warning("transcribe_audio: file not found: %s", filepath)
        return ""

    try:
        model = _get_whisper()
        result = model.transcribe(filepath, fp16=False)
        text = result.get("text", "").strip()
        logger.info("Transcription complete (%d chars)", len(text))
        return text
    except Exception as exc:
        logger.error("Whisper transcription failed: %s", exc)
        return ""


# ---------------------------------------------------------------------------
# Sentence-transformers — text embeddings
# ---------------------------------------------------------------------------

ST_MODEL_NAME = "all-MiniLM-L6-v2"


def _get_st_model():
    global _st_model
    if _st_model is None:
        with _st_lock:
            if _st_model is None:
                logger.info("Loading sentence-transformers model: %s", ST_MODEL_NAME)
                from sentence_transformers import SentenceTransformer
                _st_model = SentenceTransformer(ST_MODEL_NAME)
                logger.info("sentence-transformers model loaded.")
    return _st_model


def embed_text(text: str) -> List[float]:
    """
    Generate a 384-dim L2-normalised text embedding.

    Args:
        text: The text to embed (title, notes, mood, location, transcript).

    Returns:
        384-element list of floats.
    """
    if not text.strip():
        logger.warning("embed_text called with empty text — returning zero vector")
        return [0.0] * TEXT_EMBED_DIM

    try:
        model = _get_st_model()
        vec = model.encode(text, normalize_embeddings=True)
        return vec.tolist()
    except Exception as exc:
        logger.error("Text embedding failed: %s", exc)
        return [0.0] * TEXT_EMBED_DIM


# ---------------------------------------------------------------------------
# Sparse text embeddings — BM25-style for hybrid search (FIX 2)
# ---------------------------------------------------------------------------
# Client-side BM25 TF weighting with hash-based indexing (no vocabulary needed).
# Per the search-types skill: "BM25 — good baseline, works out-of-domain."
# This mirrors BM25 TF weighting without requiring the server-side BM25 plugin,
# making it work in local-mode Qdrant.
#
# Hash space: 0–65535 (2^16). Collision probability is negligible for diary-scale
# text (typical vocabulary <5k unique tokens per entry).

SPARSE_HASH_SPACE = 65536  # index range for hash-based term mapping


def embed_text_sparse(text: str) -> dict:
    """
    Generate a BM25-style sparse vector for hybrid text search.

    Uses log-TF weighting and a stable hash to map terms to indices.
    No global vocabulary or external model required.

    Args:
        text: The text to encode (title, notes, mood, location, transcript).

    Returns:
        Dict with 'indices' (List[int]) and 'values' (List[float]).
        Empty lists if text has no alphanumeric tokens.
        Compatible with Qdrant SparseVector(indices=..., values=...).
    """
    if not text.strip():
        return {"indices": [], "values": []}

    # Tokenise: lowercase, split on non-alphanumeric, keep 2+ char tokens
    tokens = [t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) >= 2]
    if not tokens:
        return {"indices": [], "values": []}

    # Term frequency count per hashed index
    tf: dict = {}
    for token in tokens:
        idx = hash(token) % SPARSE_HASH_SPACE
        tf[idx] = tf.get(idx, 0) + 1

    # Log-TF weighting: log(1 + tf) / log(1 + total_tokens)
    # Normalises for document length, mirrors BM25 TF sub-linear saturation
    n = len(tokens)
    log_n = math.log(1 + n)

    indices = list(tf.keys())
    values = [math.log(1 + count) / log_n for count in tf.values()]

    return {"indices": indices, "values": values}


# ---------------------------------------------------------------------------
# CLAP — neural audio embeddings (primary)
# ---------------------------------------------------------------------------
# Uses microsoft/CLAP (msclap) with laion/larger_clap_general weights.
# Output: 512-dim L2-normalised embedding.
# GPU is used automatically when torch.cuda.is_available().
#
# Falls back to librosa MFCC+mel statistics if CLAP fails to load
# or errors on a particular file, ensuring pipeline resilience.


def _get_clap_model():
    """Lazy-load and cache the CLAP model singleton."""
    global _clap_model
    if _clap_model is None:
        with _clap_lock:
            if _clap_model is None:
                logger.info("Loading CLAP model (version=%s)...", CLAP_VERSION)
                import torch
                from msclap import CLAP
                device = "cuda" if torch.cuda.is_available() else "cpu"
                logger.info("CLAP will run on: %s", device)
                _clap_model = CLAP(version=CLAP_VERSION, use_cuda=torch.cuda.is_available())
                logger.info("CLAP model loaded successfully.")
    return _clap_model


def embed_audio(filepath: str) -> List[float]:
    """
    Generate a 1024-dim audio embedding from an audio file.

    Uses CLAP (laion/larger_clap_general) for neural audio understanding.
    Automatically uses GPU when available. Falls back to librosa
    MFCC+mel statistics if CLAP is unavailable or errors.

    Args:
        filepath: Path to the audio file (WAV, MP3, OGG, WEBM, etc.).

    Returns:
        1024-element L2-normalised list of floats.
    """
    p = Path(filepath)
    if not p.exists():
        logger.warning("embed_audio: file not found: %s", filepath)
        return [0.0] * AUDIO_EMBED_DIM

    # Minimum viable audio file is at least 1 KB.
    # Files smaller than this are test stubs (e.g. b'RIFF fake wav data\n')
    # and will cause librosa to raise an exception with an empty message.
    file_size = p.stat().st_size
    if file_size < 1024:
        logger.warning(
            "embed_audio: file too small to be real audio (%d bytes): %s — skipping",
            file_size, filepath,
        )
        return [0.0] * AUDIO_EMBED_DIM

    if USE_CLAP:
        try:
            return _embed_audio_clap(filepath)
        except Exception as exc:
            logger.warning(
                "CLAP embedding failed for %s: %r — falling back to librosa",
                filepath, exc,
            )

    # Librosa fallback
    try:
        return _embed_audio_librosa(filepath)
    except Exception as exc:
        logger.error("Audio embedding failed for %s: %r", filepath, exc)
        return [0.0] * AUDIO_EMBED_DIM


def _embed_audio_clap(filepath: str) -> List[float]:
    """
    CLAP-based 1024-dim audio embedding.

    Loads audio at 44100 Hz (CLAP's native sample rate), runs the
    CLAP audio encoder, and returns an L2-normalised 1024-dim vector.
    """
    import torch

    model = _get_clap_model()

    # msclap expects a list of file paths
    audio_embeddings = model.get_audio_embeddings([filepath])
    # audio_embeddings shape: (1, 1024)
    vec = audio_embeddings[0]  # torch.Tensor or np.ndarray

    if hasattr(vec, "numpy"):
        vec = vec.detach().cpu().numpy()
    vec = np.array(vec, dtype=np.float32)

    # Replace NaN/Inf with 0
    vec = np.nan_to_num(vec, nan=0.0, posinf=0.0, neginf=0.0)

    # L2 normalise
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm

    logger.debug("CLAP embedding: dim=%d, norm=%.4f", len(vec), np.linalg.norm(vec))
    return vec.tolist()


# ---------------------------------------------------------------------------
# librosa — audio embeddings (fallback)
# ---------------------------------------------------------------------------
# Produces a 1024-dim acoustic fingerprint from:
#   - 256 MFCC mean coefficients
#   - 256 MFCC std  coefficients
#   - 256 mel-spectrogram mean per-band statistics
#   - 256 mel-spectrogram std  per-band statistics
#
# Total: 1024 dims. L2-normalised.
# Used when CLAP is unavailable or disabled (USE_CLAP = False).

def _embed_audio_librosa(filepath: str) -> List[float]:
    """librosa-based 1024-dim acoustic feature vector (fallback)."""
    import librosa

    y, sr = librosa.load(filepath, sr=22050, mono=True, duration=60)

    # 256 MFCC means + 256 MFCC stds
    mfccs = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=256)
    mfcc_mean = np.mean(mfccs, axis=1)   # (256,)
    mfcc_std  = np.std(mfccs, axis=1)    # (256,)

    # 256 mel-band means + 256 mel-band stds
    mel = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=256)
    mel_db = librosa.power_to_db(mel, ref=np.max)
    mel_mean = np.mean(mel_db, axis=1)   # (256,)
    mel_std  = np.std(mel_db, axis=1)    # (256,)

    vec = np.concatenate([mfcc_mean, mfcc_std, mel_mean, mel_std])  # (1024,)

    # Replace NaN/Inf with 0
    vec = np.nan_to_num(vec, nan=0.0, posinf=0.0, neginf=0.0)

    # L2 normalise
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm

    return vec.tolist()


# ---------------------------------------------------------------------------
# Waveform peak extraction
# ---------------------------------------------------------------------------

def extract_waveform_peaks(filepath: str, num_bars: int = 100) -> List[float]:
    """
    Extract a downsampled waveform for UI display.

    Splits the audio into `num_bars` chunks and returns the RMS amplitude
    of each chunk, normalised to [0, 1].

    Args:
        filepath: Path to the audio file.
        num_bars: Number of bars to return (default 100).

    Returns:
        List of num_bars floats in [0, 1].
    """
    if not Path(filepath).exists():
        logger.warning("extract_waveform_peaks: file not found: %s", filepath)
        return [0.0] * num_bars

    try:
        import librosa
        y, sr = librosa.load(filepath, sr=22050, mono=True, duration=60)

        chunk_size = max(1, len(y) // num_bars)
        peaks = []
        for i in range(num_bars):
            start = i * chunk_size
            end = start + chunk_size
            chunk = y[start:end]
            if len(chunk) == 0:
                peaks.append(0.0)
            else:
                rms = float(np.sqrt(np.mean(chunk ** 2)))
                peaks.append(rms)

        max_val = max(peaks) if peaks else 1.0
        if max_val > 0:
            peaks = [p / max_val for p in peaks]

        return peaks
    except Exception as exc:
        logger.error("Waveform extraction failed: %s", exc)
        return [0.0] * num_bars
