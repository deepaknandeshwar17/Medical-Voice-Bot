"""Thin wrapper around Sarvam AI STT (Saaras) and TTS (Bulbul) APIs."""
import base64

import httpx

from app.config import settings

STT_TRANSLATE_URL = "https://api.sarvam.ai/speech-to-text-translate"
TTS_URL = "https://api.sarvam.ai/text-to-speech"

_HEADERS = {"api-subscription-key": settings.sarvam_api_key}


async def transcribe(audio_bytes: bytes, filename: str = "audio.wav", content_type: str = "audio/wav") -> str:
    """Sends audio to Sarvam Saaras in translate mode; returns English text."""
    files = {"file": (filename, audio_bytes, content_type)}
    data = {"model": "saaras:v3"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(STT_TRANSLATE_URL, headers=_HEADERS, files=files, data=data)
    resp.raise_for_status()
    return resp.json()["transcript"]


async def synthesize(text: str, target_language_code: str = "en-IN") -> bytes:
    """Sends text to Sarvam Bulbul TTS; returns raw wav bytes."""
    payload = {
        "inputs": [text],
        "target_language_code": target_language_code,
        "model": "bulbul:v3",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(TTS_URL, headers=_HEADERS, json=payload)
    resp.raise_for_status()
    audio_b64 = resp.json()["audios"][0]
    return base64.b64decode(audio_b64)
