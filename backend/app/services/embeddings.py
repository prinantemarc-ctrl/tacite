"""Local embeddings via sentence-transformers (no API calls)."""

from functools import lru_cache

from ..config import EMBEDDING_MODEL


@lru_cache(maxsize=1)
def _get_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL)


def embed_texts(texts: list[str]) -> list[list[float]]:
    model = _get_model()
    vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [v.tolist() for v in vecs]


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]


def cosine(a: list[float], b: list[float]) -> float:
    # Vectors are normalized, so cosine similarity is the dot product.
    return sum(x * y for x, y in zip(a, b))
