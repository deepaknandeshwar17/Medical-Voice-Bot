"""Minimal FastAPI app for verifying external services (Sarvam, Claude) end-to-end.

Not the full pipeline yet — just debug routes to prove connectivity before
building Tier 0-3 on top of them.
"""
from pathlib import Path

import httpx
from fastapi import FastAPI, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.services import sarvam_client, claude_client

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

app = FastAPI(title="Swasthya Voice — service verification")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.allowed_origins],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/debug/transcribe")
async def debug_transcribe(audio: UploadFile):
    audio_bytes = await audio.read()
    try:
        transcript = await sarvam_client.transcribe(
            audio_bytes,
            filename=audio.filename or "audio.wav",
            content_type=audio.content_type or "audio/wav",
        )
    except httpx.HTTPStatusError as exc:
        return JSONResponse(status_code=exc.response.status_code, content={"error": exc.response.text})
    return {"transcript": transcript}


@app.post("/debug/synthesize")
async def debug_synthesize(text: str = Form(...), target_language_code: str = Form("en-IN")):
    wav_bytes = await sarvam_client.synthesize(text, target_language_code=target_language_code)
    return Response(content=wav_bytes, media_type="audio/wav")


@app.post("/debug/claude-haiku")
async def debug_claude_haiku(prompt: str = Form(...)):
    reply = await claude_client.call_haiku(system="You are a helpful assistant.", user_message=prompt)
    return {"reply": reply}


@app.post("/debug/claude-sonnet")
async def debug_claude_sonnet(prompt: str = Form(...)):
    resp = await claude_client.call_sonnet(system="You are a helpful assistant.", user_message=prompt)
    return {"reply": resp.content[0].text}


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
