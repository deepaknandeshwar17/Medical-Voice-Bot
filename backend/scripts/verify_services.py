"""Standalone smoke test for external services — no server needed.

Run from repo root: python backend/scripts/verify_services.py
Checks: Claude Haiku, Claude Sonnet, Sarvam TTS. Sarvam STT needs a sample
audio file, so it's skipped here — use the /debug/transcribe route with the
frontend mic test instead.
"""
import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import claude_client, sarvam_client  # noqa: E402


async def check_haiku():
    reply = await claude_client.call_haiku("You are terse.", "Say OK if you can hear me.")
    print(f"[claude-haiku] OK -> {reply!r}")


async def check_sonnet():
    resp = await claude_client.call_sonnet("You are terse.", "Say OK if you can hear me.")
    print(f"[claude-sonnet] OK -> {resp.content[0].text!r}")


async def check_sarvam_tts():
    audio_bytes = await sarvam_client.synthesize("Hello, this is a test.", "en-IN")
    out_path = Path(__file__).resolve().parents[1] / "cache" / "audio" / "_verify_tts.wav"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(audio_bytes)
    print(f"[sarvam-tts] OK -> wrote {out_path} ({len(audio_bytes)} bytes)")


async def main():
    checks = {
        "claude-haiku": check_haiku,
        "claude-sonnet": check_sonnet,
        "sarvam-tts": check_sarvam_tts,
    }
    for name, fn in checks.items():
        try:
            await fn()
        except httpx.HTTPStatusError as exc:
            print(f"[{name}] FAILED -> {exc} | body: {exc.response.text}")
        except Exception as exc:  # noqa: BLE001
            print(f"[{name}] FAILED -> {exc}")


if __name__ == "__main__":
    asyncio.run(main())
