from fastapi import APIRouter, Form

from app.core.pipeline import reset_conversation
from app.models.schemas import HealthResponse, ResetResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health():
    return {"status": "ok"}


@router.post("/admin/reset", response_model=ResetResponse)
async def admin_reset(conversation_id: str = Form(...)):
    reset_conversation(conversation_id)
    return {"status": "reset", "conversation_id": conversation_id}
