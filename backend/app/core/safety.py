"""Tier 0 — deterministic emergency/crisis detection. Never calls an LLM.

Runs on every turn before anything else. Match => skip everything downstream,
return the pre-approved canned reply for the matched category, in target_language.
"""
import json

import numpy as np

from app.config import REPO_ROOT
from app.services import embeddings

SAFETY_DATA_PATH = REPO_ROOT / "backend" / "data" / "safety_exemplars.json"
SIMILARITY_THRESHOLD = 0.85

_categories = json.loads(SAFETY_DATA_PATH.read_text(encoding="utf-8"))
for _cat in _categories:
    _cat["_vectors"] = embeddings.embed(_cat["example_phrases"])


def check(transcript: str) -> dict | None:
    """Returns {"category": str, "replies": {"en": ..., "hi": ..., "kn": ...}} on match, else None."""
    lowered = transcript.lower()

    for cat in _categories:
        if any(keyword in lowered for keyword in cat["keywords"]):
            return {"category": cat["category_id"], "replies": cat["replies"]}

    query_vector = embeddings.embed([transcript])[0]
    best_category = None
    best_score = -1.0
    for cat in _categories:
        score = float(np.max(cat["_vectors"] @ query_vector))
        if score > best_score:
            best_score = score
            best_category = cat

    if best_score >= SIMILARITY_THRESHOLD:
        return {"category": best_category["category_id"], "replies": best_category["replies"]}
    return None
