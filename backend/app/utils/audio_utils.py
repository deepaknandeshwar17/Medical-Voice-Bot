"""Helpers for writing live-synthesized turn audio into the cache dir."""
import uuid
from pathlib import Path

from app.config import REPO_ROOT, settings

AUDIO_CACHE_DIR = REPO_ROOT / settings.audio_cache_dir


def save_turn_audio(audio_bytes: bytes) -> str:
    """Writes a live TTS result to cache/audio/ and returns just the filename."""
    AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"turn_{uuid.uuid4().hex}.wav"
    (AUDIO_CACHE_DIR / filename).write_bytes(audio_bytes)
    return filename


def cached_filename(prefix: str, key: str, language: str) -> str:
    """Filename convention used by pregenerate_audio_cache.py for Tier 0/1 hits."""
    return f"{prefix}_{key}_{language}.wav"
