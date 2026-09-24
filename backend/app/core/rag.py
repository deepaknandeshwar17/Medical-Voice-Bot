"""Tier 2 — RAG-grounded Q&A. FAISS retrieve + Claude Haiku. Never takes actions.

System prompt is fully static (cacheable across every call, every language) —
target_language and retrieved context vary per turn, so they live in the user
message instead, per the prompt-caching structure in spec section 6.
"""
import re

from app.config import REPO_ROOT, settings
from app.services import claude_client, embeddings, vector_store

TOP_K = 3

LANGUAGE_NAMES = {"en": "English", "hi": "Hindi", "kn": "Kannada"}

# The UI always shows English text (readable regardless of who's watching the
# demo) while the audio speaks target_language — one model call produces both
# instead of a second translation call. SPOKEN comes FIRST specifically so a
# streaming caller can start synthesizing audio without waiting for the
# (audio-irrelevant) English section to finish generating.
BILINGUAL_INSTRUCTION = """Produce your reply in exactly this two-line format, nothing else:
SPOKEN: <your reply fluently in target_language — this is spoken aloud, put it first>
EN: <the same reply in English, for on-screen display — identical to SPOKEN if target_language is English>"""

# Shared between Tier 2 (rag.py) and Tier 3 (agent.py) — both produce the same
# SPOKEN/EN bilingual output, so both need the same spoken-language style rules.
STYLE_GUIDELINES = """Style rules for your reply:
- In SPOKEN specifically: use natural, flowing spoken sentences — never a numbered or \
bulleted list, never digits like "1." or "2." read aloud. If you have several items to \
mention, weave them into normal prose instead (e.g. "bring your ID, any prior records, \
and insurance if you have it") — save the EN part for bullet points if they help \
readability, since EN is only ever read on screen, never spoken aloud.
- Don't mention prices or fees unless the caller specifically asks about cost — \
otherwise it reads like a sales pitch instead of a helpful answer.
- When asking for or confirming a date, always speak it naturally (e.g. "this Friday", \
"the 24th of September", "tomorrow") — never ask the caller to give a date in a written \
format like DD-MM-YYYY or YYYY-MM-DD. Understand whatever natural date they say and \
convert it yourself for anything that needs a specific format internally."""

# "EN:" is a substring of "SPOKEN:" itself (S-P-O-K-EN-:) — if Haiku ever repeats the
# "SPOKEN:" label (a known reliability quirk, seen before with the old EN/SPOKEN pair),
# a naive search for "EN:" matches the TAIL of that second "SPOKEN:" and truncates the
# reply mid-word ("SPOK" got emitted as a chunk before this guard existed). The negative
# lookbehind ensures "EN:" only matches when it's not preceded by "SPOK".
EN_MARKER = re.compile(r"(?<!SPOK)EN:")
BILINGUAL_PATTERN = re.compile(r"SPOKEN:\s*(.*?)\s*(?<!SPOK)EN:\s*(.*)", re.DOTALL)


def parse_bilingual(text: str) -> tuple[str, str]:
    """Returns (english_display_text, target_language_spoken_text).

    Handles the model dropping the "SPOKEN:" label but still including "EN:"
    (observed in practice with the old EN-first ordering — without this, the
    raw label leaks onto the screen verbatim). Only falls back to using the
    same text for both if neither marker is present at all."""
    match = BILINGUAL_PATTERN.search(text)
    if match:
        return match.group(2).strip(), match.group(1).strip()
    en_match = EN_MARKER.search(text)
    if en_match:
        before, after = text[: en_match.start()], text[en_match.end():]
        before = before.strip()
        if before.startswith("SPOKEN:"):
            before = before[7:].strip()
        return after.strip(), before
    return text.strip(), text.strip()


SYSTEM_PROMPT = f"""You are a clinic assistant for Aarogya Clinic, a general outpatient clinic. \
You are not a medical professional and must say so if asked. You must never answer questions \
about symptoms, diagnosis, treatment, or medication dosing — for those, tell the caller to \
discuss it with a doctor during a visit. You must never state or imply that a prescription \
refill has been approved.

Answer the caller's question using ONLY the retrieved context provided below the question — \
never guess or use outside knowledge. If the retrieved context includes ANY information relevant \
to the question, share what it actually contains, even if it's incomplete (e.g. it names one \
doctor but the caller asked for "all the doctors" — tell them about the one you have, then say \
you can connect them to the front desk for the complete list). Only say you don't have the \
information at all if the retrieved context contains NOTHING relevant to the question — never \
claim to have zero information when the context actually contains something relevant.

Keep the reply short and conversational, suitable for a spoken response.

{STYLE_GUIDELINES}

{BILINGUAL_INSTRUCTION}"""

_index, _chunks = vector_store.load(str(REPO_ROOT / settings.faiss_index_path))
_summary_chunks = [c for c in _chunks if c.get("is_summary")]

MAX_HISTORY_MESSAGES = 10  # last 5 Q&A pairs — enough continuity without unbounded growth


def _build_context_text(transcript: str) -> str:
    """Normal top-k retrieval, PLUS every is_summary chunk (e.g. "all doctors",
    "all services") always included regardless of where it ranks. Relying on a summary
    chunk to win top_k=3 purely on embedding similarity is fragile — "what all services
    do you offer" scores every individual service chunk highly too (each one IS a
    service), so the summary chunk never reliably clears into the top 3 no matter how
    it's worded. Always including it removes that dependency entirely."""
    query_vector = embeddings.embed([transcript])[0]
    retrieved = vector_store.query(_index, _chunks, query_vector, k=TOP_K)

    seen_texts = {c["text"] for c in retrieved}
    for summary_chunk in _summary_chunks:
        if summary_chunk["text"] not in seen_texts:
            retrieved.append(summary_chunk)
            seen_texts.add(summary_chunk["text"])

    return "\n\n---\n\n".join(chunk["text"] for chunk in retrieved)


async def answer(
    transcript: str,
    target_language: str,
    conversation_history: list[dict] | None = None,
) -> tuple[str, str, list[dict]]:
    """Returns (display_text_english, spoken_text_target_language, updated_conversation_history).

    conversation_history is plain clean text turns (question / English answer) — NOT the
    retrieved-context scaffolding, which is only injected into the current turn's message
    so it doesn't bloat every future turn with stale retrieved chunks."""
    context_text = _build_context_text(transcript)

    language_name = LANGUAGE_NAMES.get(target_language, target_language)
    user_message = (
        f"target_language: {language_name}\n\n"
        f"Retrieved context:\n{context_text}\n\n"
        f"Question: {transcript}"
    )

    history = list(conversation_history or [])
    messages = history + [{"role": "user", "content": user_message}]
    raw_reply = await claude_client.call_haiku(system=SYSTEM_PROMPT, messages=messages)
    display_text, spoken_text = parse_bilingual(raw_reply)

    updated_history = history + [
        {"role": "user", "content": transcript},
        {"role": "assistant", "content": display_text},
    ]
    updated_history = updated_history[-MAX_HISTORY_MESSAGES:]

    return display_text, spoken_text, updated_history


# Includes Devanagari danda (।) and double danda (॥) — Hindi sentences end with these,
# not a period. Without this, Hindi replies never hit a boundary mid-stream and come
# through as one giant chunk at the end, defeating the point of streaming entirely.
# The (?!\d) guard avoids treating "Rs. 400" as a sentence boundary — an abbreviation
# period followed by a number, not an actual new sentence (observed splitting "our
# consultation costs Rs." / "400" into two audibly awkward chunks without this).
SENTENCE_BOUNDARY = re.compile(r"[.!?।॥](?:\s(?!\d)|$)")


async def answer_streaming(transcript: str, target_language: str, conversation_history: list[dict] | None = None):
    """Same as answer(), but yields spoken-language sentences as they become available
    instead of waiting for the full reply, so a caller can start TTS-ing sentence 1
    while Haiku is still writing sentence 3.

    Yields {"type": "chunk", "text": <one spoken-language sentence>} for each sentence,
    then finally {"type": "done", "display": ..., "spoken": ..., "history": [...]}.

    State machine over the raw token stream: SPOKEN comes first (see BILINGUAL_INSTRUCTION),
    so everything before the "EN:" marker is spoken-language text to chunk and emit;
    everything after is English display text, just accumulated silently.
    """
    context_text = _build_context_text(transcript)

    language_name = LANGUAGE_NAMES.get(target_language, target_language)
    user_message = (
        f"target_language: {language_name}\n\n"
        f"Retrieved context:\n{context_text}\n\n"
        f"Question: {transcript}"
    )

    history = list(conversation_history or [])
    messages = history + [{"role": "user", "content": user_message}]

    full_text = ""
    spoken_buffer = ""
    spoken_full = ""
    state = "before_spoken"  # before_spoken -> in_spoken -> in_english

    async for delta in claude_client.stream_haiku(system=SYSTEM_PROMPT, messages=messages):
        full_text += delta

        if state == "before_spoken":
            idx = full_text.find("SPOKEN:")
            if idx != -1:
                state = "in_spoken"
                spoken_buffer = full_text[idx + len("SPOKEN:"):]
            continue

        if state == "in_spoken":
            spoken_buffer += delta
            en_match = EN_MARKER.search(spoken_buffer)
            if en_match:
                # hit the English marker mid-buffer — flush whatever spoken text is
                # left before it (even without terminal punctuation), then switch over
                remaining = spoken_buffer[: en_match.start()].strip()
                if remaining:
                    spoken_full += remaining + " "
                    yield {"type": "chunk", "text": remaining}
                state = "in_english"
                continue

            while True:
                match = SENTENCE_BOUNDARY.search(spoken_buffer)
                if not match:
                    break
                cut = match.end()
                sentence = spoken_buffer[:cut].strip()
                spoken_buffer = spoken_buffer[cut:]
                if sentence:
                    spoken_full += sentence + " "
                    yield {"type": "chunk", "text": sentence}
            continue

        # state == "in_english" — just accumulating, nothing to emit until the end

    if state != "in_english":
        # Model never followed the SPOKEN:/EN: format at all — fall back to treating
        # the whole reply as both, same as the non-streaming fallback, as one chunk.
        display_text, spoken_text = parse_bilingual(full_text)
        if spoken_text:
            yield {"type": "chunk", "text": spoken_text}
    else:
        display_text, _ = parse_bilingual(full_text)
        spoken_text = spoken_full.strip()

    updated_history = history + [
        {"role": "user", "content": transcript},
        {"role": "assistant", "content": display_text},
    ]
    updated_history = updated_history[-MAX_HISTORY_MESSAGES:]

    yield {"type": "done", "display": display_text, "spoken": spoken_text, "history": updated_history}
