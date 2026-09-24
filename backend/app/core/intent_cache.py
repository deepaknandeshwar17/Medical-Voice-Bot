"""Tier 1 — canonical intent cache. Embedding match against a fixed intent set.

Hit => skip LLM + RAG entirely, caller plays the pre-synthesized audio for
intent_id + target_language. Miss => fall through to Tier 2/3 routing.
"""
import json

import numpy as np

from app.config import REPO_ROOT
from app.services import embeddings

INTENTS_PATH = REPO_ROOT / "backend" / "data" / "canonical_intents.json"

# A single absolute-score threshold doesn't cleanly separate hits from misses
# here (e.g. "is parking available" scores 0.82 against clinic_address, higher
# than some genuine "thanks" paraphrases score against their own intent).
# Requiring the top match to also beat the runner-up by a clear margin does
# separate cleanly (calibrated against real hit/miss phrases, not guessed).
ABSOLUTE_FLOOR = 0.75
MARGIN_THRESHOLD = 0.10

_intents = json.loads(INTENTS_PATH.read_text(encoding="utf-8"))
for _intent in _intents:
    _intent["_vectors"] = embeddings.embed(_intent["example_phrases"])


def check(transcript: str) -> dict | None:
    """Returns {"intent_id": str, "replies": {"en": ..., "hi": ..., "kn": ...}} on hit, else None."""
    query_vector = embeddings.embed([transcript])[0]
    scored = sorted(
        ((float(np.max(intent["_vectors"] @ query_vector)), intent) for intent in _intents),
        key=lambda pair: pair[0],
        reverse=True,
    )
    top_score, top_intent = scored[0]
    runner_up_score = scored[1][0] if len(scored) > 1 else -1.0

    if top_score >= ABSOLUTE_FLOOR and (top_score - runner_up_score) >= MARGIN_THRESHOLD:
        return {"intent_id": top_intent["intent_id"], "replies": top_intent["replies"]}
    return None
