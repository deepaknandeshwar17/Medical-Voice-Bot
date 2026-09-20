"""Local embedding model — loaded once, reused across safety/intent-cache/RAG."""
import numpy as np
from sentence_transformers import SentenceTransformer

from app.config import settings

_model = SentenceTransformer(settings.embedding_model_name)


def embed(texts: list[str]) -> np.ndarray:
    """Returns L2-normalized embeddings, shape (len(texts), dim), for cosine similarity via dot product."""
    return _model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
