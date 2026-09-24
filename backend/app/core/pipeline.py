"""Orchestrates one full turn end-to-end: STT -> tier routing -> TTS -> latency log.

Tier 0 (safety) and Tier 1 (intent cache) never touch an LLM and use
pre-synthesized audio. Tier 2 (RAG) and Tier 3 (agent) are the only tiers
that call an LLM, and their replies are synthesized live.

Tier 2 vs Tier 3 routing is a lightweight keyword heuristic: anything that
sounds like it wants an action (book/cancel/refill/talk to a human) goes to
the tool-calling agent, everything else goes to RAG. This is a deliberate
demo-scope simplification, not a learned classifier.
"""
import asyncio
import re
import time

from app.config import REPO_ROOT, settings
from app.core import agent, intent_cache, rag, safety
from app.services import sarvam_client
from app.utils.audio_utils import cached_filename, save_turn_audio
from app.utils.logging_config import log_conversation_turn, log_turn

AUDIO_CACHE_DIR = REPO_ROOT / settings.audio_cache_dir
LANGUAGE_CODES = {"en": "en-IN", "hi": "hi-IN", "kn": "kn-IN"}

ACTION_KEYWORDS = [
    "book", "cancel", "reschedule", "appointment", "refill", "prescription",
    "talk to", "speak to", "speak with", "transfer", "human", "front desk", "real person",
]

AFFIRMATIVE_PHRASES = [
    "yes please", "sounds good", "go ahead", "do it",
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "please", "alright", "correct",
]

# Matches any known affirmative phrase appearing anywhere in the transcript, not just
# as the WHOLE transcript — "sure, go ahead" previously failed because it was checked
# for exact equality against the phrase set instead of containment (see engineering log).
# Longer phrases listed first so "yes please" matches as one unit before "yes" alone would.
AFFIRMATIVE_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in AFFIRMATIVE_PHRASES) + r")\b", re.IGNORECASE
)

INVITES_ACTION_PATTERN = re.compile(
    r"(would you like|do you want|shall i|should i).{0,40}"
    r"(book|schedule|appointment|cancel|refill|transfer)",
    re.IGNORECASE,
)

# in-memory per-conversation state — fine for a local demo, not persisted across restarts
_conversations: dict[str, list[dict]] = {}       # Tier 3 (agent) message history, Anthropic tool-call format
_rag_histories: dict[str, list[dict]] = {}       # Tier 2 (RAG) message history, plain text turns
_last_invited_action: dict[str, bool] = {}       # did the last reply in this conversation invite an action?


def _looks_like_action(transcript: str) -> bool:
    lowered = transcript.lower()
    return any(keyword in lowered for keyword in ACTION_KEYWORDS)


def _is_affirmative(transcript: str) -> bool:
    return bool(AFFIRMATIVE_PATTERN.search(transcript.strip()))


def _reply_invites_action(reply_text: str) -> bool:
    return bool(INVITES_ACTION_PATTERN.search(reply_text))


async def run_turn(
    audio_bytes: bytes,
    filename: str,
    content_type: str,
    target_language: str,
    conversation_id: str,
) -> dict:
    t_total_start = time.perf_counter()
    latency = {"stt": 0, "routing": 0, "llm": 0, "tts": 0, "total": 0}

    t0 = time.perf_counter()
    transcript = await sarvam_client.transcribe(audio_bytes, filename=filename, content_type=content_type)
    latency["stt"] = round((time.perf_counter() - t0) * 1000)

    return await _route_and_respond(transcript, target_language, conversation_id, latency, t_total_start)


async def run_text_turn(text: str, target_language: str, conversation_id: str) -> dict:
    """Same as run_turn but skips STT entirely — for typed input and quick-action chips."""
    t_total_start = time.perf_counter()
    latency = {"stt": 0, "routing": 0, "llm": 0, "tts": 0, "total": 0}
    return await _route_and_respond(text, target_language, conversation_id, latency, t_total_start)


async def _route_and_respond(
    transcript: str,
    target_language: str,
    conversation_id: str,
    latency: dict,
    t_total_start: float,
) -> dict:
    if not transcript.strip():
        # Sarvam STT can return an empty transcript for noise/silence picked up by
        # hands-free VAD false-triggers. Short-circuit before any LLM/TTS call —
        # nothing was actually said, so there's nothing to route or respond to.
        latency["total"] = round((time.perf_counter() - t_total_start) * 1000)
        return {
            "transcript": "",
            "reply_text": "",
            "audio_url": "",
            "tier": "noop",
            "transfer_to_human": False,
            "latency_ms": latency,
        }

    t0 = time.perf_counter()
    safety_hit = safety.check(transcript)
    intent_hit = None if safety_hit else intent_cache.check(transcript)
    latency["routing"] = round((time.perf_counter() - t0) * 1000)

    tier: str
    reply_text: str          # always English — what's shown on screen
    reply_spoken: str | None = None  # target-language text actually sent to TTS (Tier 2/3 only)
    transfer = False
    audio_filename: str | None = None

    safety_category: str | None = None

    if safety_hit:
        tier = "0"
        safety_category = safety_hit["category"]
        reply_text = safety_hit["replies"]["en"]
        audio_filename = cached_filename("safety", safety_hit["category"], target_language)
        transfer = True

    elif intent_hit:
        tier = "1"
        reply_text = intent_hit["replies"]["en"]
        audio_filename = cached_filename("intent", intent_hit["intent_id"], target_language)
        transfer = intent_hit["intent_id"] == "human_handoff_request"

    elif (
        conversation_id in _conversations
        or _looks_like_action(transcript)
        or (_last_invited_action.get(conversation_id, False) and _is_affirmative(transcript))
    ):
        # Once a conversation has engaged the agent (e.g. mid-booking), stay in Tier 3
        # for follow-up turns even if they don't individually contain an action keyword
        # ("at 10, name is X, phone is Y" has no action verb but must continue the flow).
        # Also route here if the PREVIOUS reply invited an action ("would you like to
        # schedule?") and this turn is a bare "yes" — that has no action keyword either,
        # but only makes sense as an answer to the invitation.
        # Tradeoff: after a booking wraps up, an unrelated question in the same
        # conversation still goes to the agent rather than back to grounded RAG.
        tier = "3"
        t0 = time.perf_counter()
        history = _conversations.get(conversation_id, [])
        if not history:
            # First Tier 3 turn this conversation — if Tier 2 (RAG) already discussed
            # something in this same conversation, seed the agent with that context
            # instead of starting blind (e.g. "yes" after "would you like to book for
            # your cough?" should let the agent know it's a cough, not ask from scratch).
            rag_context = _rag_histories.get(conversation_id, [])
            if rag_context:
                history = list(rag_context[-4:])
        reply_text, reply_spoken, updated_history, transfer = await agent.handle_turn(transcript, target_language, history)
        _conversations[conversation_id] = updated_history
        latency["llm"] = round((time.perf_counter() - t0) * 1000)

    else:
        tier = "2"
        t0 = time.perf_counter()
        rag_history = _rag_histories.get(conversation_id, [])
        reply_text, reply_spoken, updated_rag_history = await rag.answer(transcript, target_language, rag_history)
        _rag_histories[conversation_id] = updated_rag_history
        latency["llm"] = round((time.perf_counter() - t0) * 1000)

    if audio_filename is None:
        t0 = time.perf_counter()
        text_for_tts = reply_spoken or reply_text
        audio_bytes_out = await sarvam_client.synthesize(text_for_tts, target_language_code=LANGUAGE_CODES[target_language])
        audio_filename = save_turn_audio(audio_bytes_out)
        latency["tts"] = round((time.perf_counter() - t0) * 1000)

    _last_invited_action[conversation_id] = _reply_invites_action(reply_text)

    latency["total"] = round((time.perf_counter() - t_total_start) * 1000)

    if tier == "0":
        log_turn(conversation_id=conversation_id, tier=tier, category=safety_category, latency_ms=latency)
    else:
        log_turn(conversation_id=conversation_id, tier=tier, transcript=transcript, latency_ms=latency)

    log_conversation_turn(conversation_id, tier, transcript, reply_text)

    return {
        "transcript": transcript,
        "reply_text": reply_text,
        "audio_url": f"/audio/{audio_filename}",
        "tier": tier,
        "transfer_to_human": transfer,
        "latency_ms": latency,
    }


async def stream_text_turn(text: str, target_language: str, conversation_id: str):
    """Streaming counterpart to run_text_turn — see _stream_route_and_respond."""
    t_total_start = time.perf_counter()
    async for event in _stream_route_and_respond(text, target_language, conversation_id, 0, t_total_start):
        yield event


async def stream_turn(
    audio_bytes: bytes,
    filename: str,
    content_type: str,
    target_language: str,
    conversation_id: str,
):
    """Streaming counterpart to run_turn — STT still runs as one blocking call (Sarvam's
    non-streaming STT is what we're set up for), then the same streaming logic applies."""
    t_total_start = time.perf_counter()
    t0 = time.perf_counter()
    transcript = await sarvam_client.transcribe(audio_bytes, filename=filename, content_type=content_type)
    stt_ms = round((time.perf_counter() - t0) * 1000)
    async for event in _stream_route_and_respond(transcript, target_language, conversation_id, stt_ms, t_total_start):
        yield event


async def _stream_route_and_respond(
    transcript: str,
    target_language: str,
    conversation_id: str,
    stt_ms: int,
    t_total_start: float,
):
    """Tier 2 (RAG) only streams for real — yields {"type": "chunk", "audio_url": ..., "seq": n}
    per sentence as it's synthesized, then a final {"type": "done", ...} matching the shape
    run_turn/run_text_turn return. Tier 0/1/3 aren't worth streaming (0/1 are already
    sub-second with no LLM call; 3's latency is mostly sequential tool round-trips that
    streaming can't shorten) — they fall back to the existing non-streaming path and are
    delivered as a single "done" event, so the caller doesn't need to know the tier in
    advance to pick a code path."""
    if not transcript.strip():
        yield {
            "type": "done",
            "transcript": "",
            "reply_text": "",
            "audio_url": "",
            "tier": "noop",
            "transfer_to_human": False,
            "latency_ms": {"stt": stt_ms, "routing": 0, "llm": 0, "tts": 0, "total": 0},
        }
        return

    safety_hit = safety.check(transcript)
    intent_hit = None if safety_hit else intent_cache.check(transcript)
    is_tier2 = not safety_hit and not intent_hit and not (
        conversation_id in _conversations
        or _looks_like_action(transcript)
        or (_last_invited_action.get(conversation_id, False) and _is_affirmative(transcript))
    )

    if not is_tier2:
        latency = {"stt": stt_ms, "routing": 0, "llm": 0, "tts": 0, "total": 0}
        result = await _route_and_respond(transcript, target_language, conversation_id, latency, t_total_start)
        yield {"type": "done", **result}
        return

    latency = {"stt": stt_ms, "routing": 0, "llm": 0, "tts": 0, "total": 0}
    rag_history = _rag_histories.get(conversation_id, [])

    # Real overlap, not just sequential-but-chunked: each sentence's TTS call is fired
    # as a background task the moment the sentence is ready, so Haiku keeps generating
    # sentence N+1 while sentence N is being synthesized — the whole point of streaming.
    # A naive "await TTS inside the loop that reads the LLM stream" (the first version of
    # this) blocks the LLM stream while TTS runs, so nothing overlaps and total latency
    # gets WORSE (N separate TTS round-trips, none overlapped) even though first-chunk
    # latency looks fine. Producer/consumer over an asyncio.Queue avoids that: the
    # producer reads the LLM stream and only ever fires-and-forgets TTS tasks (never
    # awaits them inline), the consumer drains completed results in order and yields
    # them to the caller as soon as each is ready, running concurrently with the producer.
    result_queue: asyncio.Queue = asyncio.Queue()
    produced = {"display": "", "history": rag_history, "text_done_at": None}
    llm_start = time.perf_counter()

    async def synthesize_and_enqueue(sentence_text: str, seq_num: int) -> None:
        audio_bytes_out = await sarvam_client.synthesize(
            sentence_text, target_language_code=LANGUAGE_CODES[target_language]
        )
        await result_queue.put(("chunk", seq_num, audio_bytes_out))

    async def produce() -> None:
        seq_num = 0
        tts_tasks = []
        async for event in rag.answer_streaming(transcript, target_language, rag_history):
            if event["type"] == "chunk":
                seq_num += 1
                tts_tasks.append(asyncio.create_task(synthesize_and_enqueue(event["text"], seq_num)))
            else:  # "done"
                produced["display"] = event["display"]
                produced["history"] = event["history"]
        produced["text_done_at"] = time.perf_counter()  # LLM finished writing; TTS may still be finishing up
        if tts_tasks:
            await asyncio.gather(*tts_tasks)
        await result_queue.put(("llm_done", None, None))

    producer_task = asyncio.create_task(produce())

    next_seq_to_emit = 1
    buffered: dict[int, bytes] = {}
    first_chunk_ms: int | None = None

    while True:
        kind, seq_num, audio_bytes_out = await result_queue.get()
        if kind == "llm_done":
            break
        buffered[seq_num] = audio_bytes_out
        while next_seq_to_emit in buffered:
            if first_chunk_ms is None:
                first_chunk_ms = round((time.perf_counter() - llm_start) * 1000)
            audio_filename = save_turn_audio(buffered.pop(next_seq_to_emit))
            yield {"type": "chunk", "audio_url": f"/audio/{audio_filename}", "seq": next_seq_to_emit}
            next_seq_to_emit += 1

    await producer_task  # propagates any exception from the LLM stream or a TTS task

    display_text = produced["display"]
    updated_rag_history = produced["history"]

    # llm = wall-clock time to finish generating all text. tts = the ADDITIONAL wall-clock
    # time needed after that for any still-running TTS calls to finish (the "tail" — TTS
    # work that happened DURING text generation is overlapped/free and doesn't show up
    # here, which is the whole point of streaming). These two are genuinely additive,
    # unlike naively summing each chunk's own TTS duration (which double-counts time
    # spent running concurrently and can go negative once subtracted from wall-clock total).
    t_end = time.perf_counter()
    latency["llm"] = round((produced["text_done_at"] - llm_start) * 1000)
    latency["tts"] = round((t_end - produced["text_done_at"]) * 1000)
    latency["total"] = round((t_end - t_total_start) * 1000)

    _rag_histories[conversation_id] = updated_rag_history
    _last_invited_action[conversation_id] = _reply_invites_action(display_text)

    log_turn(
        conversation_id=conversation_id,
        tier="2",
        transcript=transcript,
        latency_ms=latency,
        streamed=True,
        first_chunk_ms=first_chunk_ms,
    )
    log_conversation_turn(conversation_id, "2", transcript, display_text)

    yield {
        "type": "done",
        "transcript": transcript,
        "reply_text": display_text,
        "audio_url": "",  # audio was already delivered as "chunk" events, not one final file
        "tier": "2",
        "transfer_to_human": False,
        "latency_ms": latency,
    }


def reset_conversation(conversation_id: str) -> None:
    _conversations.pop(conversation_id, None)
    _rag_histories.pop(conversation_id, None)
    _last_invited_action.pop(conversation_id, None)
