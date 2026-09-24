import json

import httpx
from fastapi import APIRouter, Form, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from app.core import pipeline
from app.models.schemas import VoiceTurnResponse

router = APIRouter()


@router.post("/voice/turn", response_model=VoiceTurnResponse)
async def voice_turn(
    audio: UploadFile,
    target_language: str = Form(...),
    conversation_id: str = Form(...),
):
    if target_language not in ("en", "hi", "kn"):
        return JSONResponse(status_code=400, content={"error": "target_language must be one of: en, hi, kn"})

    audio_bytes = await audio.read()
    try:
        result = await pipeline.run_turn(
            audio_bytes=audio_bytes,
            filename=audio.filename or "audio.wav",
            content_type=audio.content_type or "audio/wav",
            target_language=target_language,
            conversation_id=conversation_id,
        )
    except httpx.HTTPStatusError as exc:
        return JSONResponse(
            status_code=502,
            content={"error": "upstream_service_error", "message": exc.response.text},
        )
    return result


@router.post("/voice/turn/stream")
async def voice_turn_stream(
    audio: UploadFile,
    target_language: str = Form(...),
    conversation_id: str = Form(...),
):
    """Streaming counterpart to /voice/turn — see /voice/text/stream for the event shape."""
    if target_language not in ("en", "hi", "kn"):
        return JSONResponse(status_code=400, content={"error": "target_language must be one of: en, hi, kn"})

    audio_bytes = await audio.read()
    filename = audio.filename or "audio.wav"
    content_type = audio.content_type or "audio/wav"

    async def event_generator():
        try:
            async for event in pipeline.stream_turn(audio_bytes, filename, content_type, target_language, conversation_id):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except httpx.HTTPStatusError as exc:
            error_event = {"type": "error", "message": exc.response.text}
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/voice/text/stream")
async def voice_text_stream(
    text: str = Form(...),
    target_language: str = Form(...),
    conversation_id: str = Form(...),
):
    """Experimental streaming counterpart to /voice/text, Tier 2 only (see
    pipeline.stream_text_turn). Server-Sent Events: a sequence of {"type":"chunk",...}
    events as each sentence's audio becomes ready, then one {"type":"done",...} with
    the same shape /voice/text returns. Additive — /voice/text is untouched."""
    if target_language not in ("en", "hi", "kn"):
        return JSONResponse(status_code=400, content={"error": "target_language must be one of: en, hi, kn"})

    async def event_generator():
        try:
            async for event in pipeline.stream_text_turn(text, target_language, conversation_id):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except httpx.HTTPStatusError as exc:
            error_event = {"type": "error", "message": exc.response.text}
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/voice/text", response_model=VoiceTurnResponse)
async def voice_text(
    text: str = Form(...),
    target_language: str = Form(...),
    conversation_id: str = Form(...),
):
    """Same as /voice/turn but skips STT — for typed input and quick-action chips."""
    if target_language not in ("en", "hi", "kn"):
        return JSONResponse(status_code=400, content={"error": "target_language must be one of: en, hi, kn"})

    try:
        result = await pipeline.run_text_turn(
            text=text,
            target_language=target_language,
            conversation_id=conversation_id,
        )
    except httpx.HTTPStatusError as exc:
        return JSONResponse(
            status_code=502,
            content={"error": "upstream_service_error", "message": exc.response.text},
        )
    return result
