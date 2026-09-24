"""Chunks backend/data/clinic_kb/ and builds the FAISS index for Tier 2 RAG.

Run from repo root: python backend/scripts/build_index.py

emergency_policy.md is intentionally excluded — it informs Tier 0's canned
response wording at build time, it is never retrieved live during a call.
"""
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services import embeddings, vector_store  # noqa: E402
from app.config import settings  # noqa: E402

KB_DIR = REPO_ROOT / "backend" / "data" / "clinic_kb"


def chunk_json_array_with_summary(path: Path, summary_title: str, line_fn) -> list[dict]:
    """Individual per-item chunks (good for "does Dr. X work Saturdays" / "how much is
    Blood Tests") PLUS one consolidated chunk listing every item together (good for
    "who are your doctors" / "what all services do you offer"), tagged is_summary=True.

    Relying on the summary chunk to win top_k=3 purely on embedding similarity turned
    out fragile: it worked for doctors (usually ranked #1-3) but failed for services —
    "what all services do you offer" scores every individual service chunk highly too
    (each one IS a service, so they all match the general topic), so the summary chunk
    never cleared into the top 3 regardless of how it was worded. rag.py always includes
    every is_summary chunk in context on top of normal top-k retrieval instead, so this
    doesn't depend on winning a ranking contest at all."""
    items = json.loads(path.read_text(encoding="utf-8"))
    chunks = [{"text": json.dumps(item, ensure_ascii=False), "source": path.name} for item in items]

    summary_text = summary_title + "\n" + "\n".join(line_fn(item) for item in items)
    chunks.append({"text": summary_text, "source": path.name, "is_summary": True})

    return chunks


def chunk_json_object(path: Path) -> list[dict]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    return [{"text": json.dumps(obj, ensure_ascii=False), "source": path.name}]


def chunk_markdown_by_heading(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    sections = re.split(r"(?=^## )", text, flags=re.MULTILINE)
    chunks = []
    for section in sections:
        section = section.strip()
        if not section or section.startswith("# "):
            continue
        chunks.append({"text": section, "source": path.name})
    return chunks


def build_chunks() -> list[dict]:
    chunks = []
    chunks += chunk_json_array_with_summary(
        KB_DIR / "doctors.json",
        "All doctors at Aarogya Clinic:",
        lambda d: f"{d['name']} — {d['specialty']}, available {', '.join(d['available_days'])}, {d['timing']}",
    )
    chunks += chunk_json_array_with_summary(
        KB_DIR / "services.json",
        "All services at Aarogya Clinic:",
        lambda s: f"{s['name']} — {s['description']} ({s['price_inr']} rupees)",
    )
    chunks += chunk_json_object(KB_DIR / "timings.json")
    chunks += chunk_markdown_by_heading(KB_DIR / "faq.md")
    chunks += chunk_markdown_by_heading(KB_DIR / "appointment_policy.md")
    chunks += chunk_markdown_by_heading(KB_DIR / "prescription_policy.md")
    return chunks


def main():
    chunks = build_chunks()
    texts = [c["text"] for c in chunks]
    vectors = embeddings.embed(texts)
    vector_store.build(vectors, chunks, str(REPO_ROOT / settings.faiss_index_path))
    print(f"Built FAISS index: {len(chunks)} chunks -> {settings.faiss_index_path}")


if __name__ == "__main__":
    main()
