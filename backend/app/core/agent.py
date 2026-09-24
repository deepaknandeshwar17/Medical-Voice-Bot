"""Tier 3 — tool-calling agent. Claude Sonnet + tool schemas + SQLite.

System prompt is fully static (cacheable) — target_language and the transcript
go in the user turn, same pattern as Tier 2. Runs a tool-use loop: execute
whatever Sonnet calls, feed the structured result back, repeat until Sonnet
produces a final text reply (or a safety cap is hit).
"""
import json
from datetime import date

from app.core.rag import BILINGUAL_INSTRUCTION, LANGUAGE_NAMES, STYLE_GUIDELINES, parse_bilingual
from app.core.tools import TOOL_FUNCTIONS, TOOL_SCHEMAS
from app.services import claude_client

MAX_TOOL_ITERATIONS = 5

SYSTEM_PROMPT = f"""You are a clinic assistant for Aarogya Clinic, a general outpatient clinic, \
handling appointment booking, cancellation, prescription refill requests, and human handoff \
requests over the phone.

You are not a medical professional and must say so if asked. You must never answer questions \
about symptoms, diagnosis, treatment, or medication dosing. You must never state or imply that \
a prescription refill has been approved — refill requests are only ever logged for doctor review.

Use the available tools to check availability, book, cancel, look up clinic hours, log refill \
requests, or transfer to a human. Before finalizing a booking or cancellation, confirm the \
key details back to the caller if anything is ambiguous (e.g. which doctor, which date, whose \
appointment). Today's date will be given to you if relevant to the request.

Keep replies short and conversational, suitable for a spoken response. The rules below apply \
ONLY to your final reply to the caller, never to internal tool-call turns:

{STYLE_GUIDELINES}

{BILINGUAL_INSTRUCTION}"""


def _run_tool(name: str, tool_input: dict) -> dict:
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return {"error": "unknown_tool", "message": f"No such tool: {name}"}
    try:
        return fn(**tool_input)
    except Exception as exc:  # noqa: BLE001 — a bad tool call must never crash the turn
        return {"error": "tool_execution_failed", "message": str(exc)}


async def handle_turn(
    transcript: str,
    target_language: str,
    conversation_history: list[dict] | None = None,
) -> tuple[str, str, list[dict], bool]:
    """Returns (display_text_english, spoken_text_target_language, updated_conversation_history, transfer_to_human)."""
    messages = list(conversation_history or [])
    language_name = LANGUAGE_NAMES.get(target_language, target_language)
    user_turn = f"target_language: {language_name}\ntoday's date: {date.today().isoformat()}\n\n{transcript}"
    messages.append({"role": "user", "content": user_turn})

    transfer_requested = False

    for _ in range(MAX_TOOL_ITERATIONS):
        resp = await claude_client.call_sonnet(system=SYSTEM_PROMPT, messages=messages, tools=TOOL_SCHEMAS)
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            final_text = "".join(block.text for block in resp.content if block.type == "text")
            display_text, spoken_text = parse_bilingual(final_text)
            return display_text, spoken_text, messages, transfer_requested

        tool_results = []
        for block in resp.content:
            if block.type == "tool_use":
                if block.name == "transfer_to_human":
                    transfer_requested = True
                result = _run_tool(block.name, block.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
        messages.append({"role": "user", "content": tool_results})

    fallback = "I'm having trouble completing that right now — let me connect you to the front desk."
    return fallback, fallback, messages, True
