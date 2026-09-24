"""Synthesizes Tier 0/1 canned audio for every category/intent x language, once.

Run from repo root: python backend/scripts/pregenerate_audio_cache.py
Output: backend/cache/audio/safety_<category_id>_<lang>.wav
        backend/cache/audio/intent_<intent_id>_<lang>.wav
Re-run whenever safety_exemplars.json or canonical_intents.json replies change.
"""
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import settings  # noqa: E402
from app.services import sarvam_client  # noqa: E402

AUDIO_CACHE_DIR = REPO_ROOT / settings.audio_cache_dir
LANGUAGE_CODES = {"en": "en-IN", "hi": "hi-IN", "kn": "kn-IN"}


async def synth_all(entries: list[dict], id_field: str, prefix: str):
    for entry in entries:
        entry_id = entry[id_field]
        for lang, text in entry["replies"].items():
            out_path = AUDIO_CACHE_DIR / f"{prefix}_{entry_id}_{lang}.wav"
            audio_bytes = await sarvam_client.synthesize(text, target_language_code=LANGUAGE_CODES[lang])
            out_path.write_bytes(audio_bytes)
            print(f"wrote {out_path.name} ({len(audio_bytes)} bytes)")


async def main():
    AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    safety_categories = json.loads((REPO_ROOT / "backend/data/safety_exemplars.json").read_text(encoding="utf-8"))
    await synth_all(safety_categories, "category_id", "safety")

    intents = json.loads((REPO_ROOT / "backend/data/canonical_intents.json").read_text(encoding="utf-8"))
    await synth_all(intents, "intent_id", "intent")


if __name__ == "__main__":
    asyncio.run(main())
