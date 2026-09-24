"""Swasthya Voice backend — FastAPI app.

Mounts the real /voice/turn and /health/admin routes, the audio cache (so
/audio_url values from a turn response are servable), a handful of /debug/*
routes kept around from initial service-connectivity verification, and the
plain HTML/CSS/JS frontend (StaticFiles, no build step, same origin).
"""
from pathlib import Path

import httpx
from fastapi import FastAPI, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api import routes_admin, routes_voice
from app.config import settings
from app.services import sarvam_client, claude_client

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = REPO_ROOT / "frontend"
AUDIO_CACHE_DIR = REPO_ROOT / settings.audio_cache_dir

app = FastAPI(title="Swasthya Voice")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.allowed_origins],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_voice.router)
app.include_router(routes_admin.router)


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
    reply = await claude_client.call_haiku(
        system="You are a helpful assistant.", messages=[{"role": "user", "content": prompt}]
    )
    return {"reply": reply}


@app.post("/debug/claude-sonnet")
async def debug_claude_sonnet(prompt: str = Form(...)):
    resp = await claude_client.call_sonnet(
        system="You are a helpful assistant.", messages=[{"role": "user", "content": prompt}]
    )
    return {"reply": resp.content[0].text}


AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/audio", StaticFiles(directory=str(AUDIO_CACHE_DIR)), name="audio")
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
