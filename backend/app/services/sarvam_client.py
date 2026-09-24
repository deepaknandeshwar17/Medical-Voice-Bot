"""Thin wrapper around Sarvam AI STT (Saaras) and TTS (Bulbul) APIs."""
import base64
import io
import wave

import httpx

from app.config import settings

STT_TRANSLATE_URL = "https://api.sarvam.ai/speech-to-text-translate"
TTS_URL = "https://api.sarvam.ai/text-to-speech"

# Sarvam TTS rejects any single input string over 500 characters.
TTS_MAX_CHARS = 500

_HEADERS = {"api-subscription-key": settings.sarvam_api_key}


async def transcribe(audio_bytes: bytes, filename: str = "audio.wav", content_type: str = "audio/wav") -> str:
    """Sends audio to Sarvam Saaras in translate mode; returns English text."""
    files = {"file": (filename, audio_bytes, content_type)}
    data = {"model": "saaras:v3"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(STT_TRANSLATE_URL, headers=_HEADERS, files=files, data=data)
    resp.raise_for_status()
    return resp.json()["transcript"]


def _chunk_text(text: str, max_chars: int = TTS_MAX_CHARS) -> list[str]:
    """Splits on sentence boundaries first, packing greedily under max_chars.
    Falls back to a hard character split for any single sentence that's still too long."""
    sentences = [s.strip() for s in text.replace("\n", " ").split(". ") if s.strip()]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}." if current else f"{sentence}."
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            if len(sentence) + 1 <= max_chars:
                current = f"{sentence}."
            else:
                for i in range(0, len(sentence), max_chars):
                    chunks.append(sentence[i : i + max_chars])
                current = ""
    if current:
        chunks.append(current)
    return chunks or [text[:max_chars]]


def _concat_wavs(wav_byte_chunks: list[bytes]) -> bytes:
    if len(wav_byte_chunks) == 1:
        return wav_byte_chunks[0]

    frames = []
    params = None
    for chunk in wav_byte_chunks:
        with wave.open(io.BytesIO(chunk), "rb") as w:
            params = params or w.getparams()
            frames.append(w.readframes(w.getnframes()))

    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setparams(params)
        for f in frames:
            w.writeframes(f)
    return out.getvalue()


async def _synthesize_one(text: str, target_language_code: str) -> bytes:
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


async def synthesize(text: str, target_language_code: str = "en-IN") -> bytes:
    """Sends text to Sarvam Bulbul TTS; returns raw wav bytes.
    Transparently chunks and re-concatenates text over Sarvam's 500-char input limit."""
    chunks = _chunk_text(text)
    wav_chunks = [await _synthesize_one(chunk, target_language_code) for chunk in chunks]
    return _concat_wavs(wav_chunks)
