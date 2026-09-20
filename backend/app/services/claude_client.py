"""Thin wrapper around Anthropic Claude — Haiku for RAG/Q&A, Sonnet for tool-calling."""
from anthropic import AsyncAnthropic

from app.config import settings

HAIKU_MODEL = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-5"

_client = AsyncAnthropic(api_key=settings.anthropic_api_key)


async def call_haiku(system: str, user_message: str, max_tokens: int = 512) -> str:
    resp = await _client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    return resp.content[0].text


async def call_sonnet(system: str, user_message: str, max_tokens: int = 512, tools=None):
    kwargs = {}
    if tools:
        kwargs["tools"] = tools
    resp = await _client.messages.create(
        model=SONNET_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_message}],
        **kwargs,
    )
    return resp
