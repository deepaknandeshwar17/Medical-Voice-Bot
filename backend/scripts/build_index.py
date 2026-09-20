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


def chunk_json_array(path: Path) -> list[dict]:
    items = json.loads(path.read_text(encoding="utf-8"))
    return [{"text": json.dumps(item, ensure_ascii=False), "source": path.name} for item in items]


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
    chunks += chunk_json_array(KB_DIR / "doctors.json")
    chunks += chunk_json_array(KB_DIR / "services.json")
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
