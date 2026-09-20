"""FAISS flat index build/load/query over the clinic KB chunks."""
import json
from pathlib import Path

import faiss
import numpy as np

INDEX_FILENAME = "index.faiss"
METADATA_FILENAME = "metadata.json"


def build(embeddings: np.ndarray, chunks: list[dict], index_dir: str) -> None:
    """chunks[i] = {"text": ..., "source": ...}, aligned with embeddings[i]."""
    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings)

    out_dir = Path(index_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(out_dir / INDEX_FILENAME))
    (out_dir / METADATA_FILENAME).write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")


def load(index_dir: str):
    out_dir = Path(index_dir)
    index = faiss.read_index(str(out_dir / INDEX_FILENAME))
    chunks = json.loads((out_dir / METADATA_FILENAME).read_text(encoding="utf-8"))
    return index, chunks


def query(index, chunks: list[dict], query_embedding: np.ndarray, k: int = 3) -> list[dict]:
    scores, indices = index.search(query_embedding.reshape(1, -1), k)
    return [chunks[i] for i in indices[0] if i != -1]
