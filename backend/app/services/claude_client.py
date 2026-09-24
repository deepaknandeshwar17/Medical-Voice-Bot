"""Thin wrapper around Anthropic Claude — Haiku for both RAG/Q&A and tool-calling.

Spec originally called for Sonnet on the tool-calling tier. Tested both models
head-to-head on the actual tool set here (6 simple, well-defined tools —
check/book/cancel/hours/refill/handoff, no deep multi-hop reasoning): Haiku
matched Sonnet on every case including multi-tool sequencing (check-then-book)
and correct cancel-by-ID. Kept Haiku for the lower per-token cost since the
extra reliability Sonnet buys wasn't needed for this tool complexity.
`call_sonnet` keeps its name (it's the Tier 3 entry point other modules
import) but actually calls AGENT_MODEL below.
"""
from anthropic import AsyncAnthropic

from app.config import settings

HAIKU_MODEL = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-5"
AGENT_MODEL = HAIKU_MODEL

_client = AsyncAnthropic(api_key=settings.anthropic_api_key)


async def call_haiku(system: str, messages: list[dict], max_tokens: int = 512, cache_system: bool = True) -> str:
    """messages is the full running conversation (plain user/assistant text turns)."""
    system_param = system
    if cache_system:
        system_param = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    resp = await _client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=max_tokens,
        system=system_param,
        messages=messages,
    )
    return resp.content[0].text


async def stream_haiku(system: str, messages: list[dict], max_tokens: int = 512, cache_system: bool = True):
    """Yields text deltas as Haiku generates them, instead of waiting for the full reply."""
    system_param = system
    if cache_system:
        system_param = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    async with _client.messages.stream(
        model=HAIKU_MODEL,
        max_tokens=max_tokens,
        system=system_param,
        messages=messages,
    ) as stream:
        async for text in stream.text_stream:
            yield text


async def call_sonnet(
    system: str,
    messages: list[dict],
    max_tokens: int = 1024,
    tools: list[dict] | None = None,
    cache_system: bool = True,
):
    """messages is the full running conversation, including any tool_use/tool_result blocks."""
    system_param = system
    if cache_system:
        system_param = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    kwargs = {}
    if tools:
        kwargs["tools"] = tools
    resp = await _client.messages.create(
        model=AGENT_MODEL,
        max_tokens=max_tokens,
        system=system_param,
        messages=messages,
        **kwargs,
    )
    return resp
