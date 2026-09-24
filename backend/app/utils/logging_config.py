"""Structured per-turn logging — one JSON line per conversation turn, with per-stage latency.

This is a first-class feature per the project spec: the demo should be able to
show *why* a turn was fast or slow, and which tier handled it.

Also writes a plain-text human-readable transcript per conversation (one file
per conversation_id, in logs/conversations/) purely as a debugging aid — not
a spec feature, just so a full conversation can be re-read after the fact if
something goes wrong. Unlike the JSON log, this one includes Tier 0 (safety)
transcripts too, since the point is to see exactly what happened.
"""
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from app.config import REPO_ROOT, settings

LOG_DIR = REPO_ROOT / "backend" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

CONVERSATIONS_DIR = LOG_DIR / "conversations"
CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)

_logger = logging.getLogger("swasthya_voice.turns")
_logger.setLevel(settings.log_level)
_logger.propagate = False

if not _logger.handlers:
    file_handler = logging.FileHandler(LOG_DIR / "turns.jsonl", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(console_handler)


def log_turn(**fields) -> None:
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), **fields}
    _logger.info(json.dumps(record, ensure_ascii=False))


# conversation_id -> file path, assigned once per conversation (at its first turn) so the
# filename sorts chronologically by start time — makes the most recent conversation easy
# to find without having to check file metadata.
_conversation_files: dict[str, Path] = {}


def log_conversation_turn(conversation_id: str, tier: str, transcript: str, reply_text: str) -> None:
    if conversation_id not in _conversation_files:
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", conversation_id) or "unknown"
        start_stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
        _conversation_files[conversation_id] = CONVERSATIONS_DIR / f"{start_stamp}_{safe_id}.txt"
    path = _conversation_files[conversation_id]

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] YOU: {transcript}\n")
        f.write(f"[{timestamp}] BOT (tier {tier}): {reply_text}\n\n")
