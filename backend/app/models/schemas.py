from pydantic import BaseModel


class LatencyBreakdown(BaseModel):
    stt: int
    routing: int
    llm: int
    tts: int
    total: int


class VoiceTurnResponse(BaseModel):
    transcript: str
    reply_text: str
    audio_url: str
    tier: str
    transfer_to_human: bool
    latency_ms: LatencyBreakdown


class HealthResponse(BaseModel):
    status: str


class ResetResponse(BaseModel):
    status: str
    conversation_id: str
