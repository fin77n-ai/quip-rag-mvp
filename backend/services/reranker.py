"""
Cross-encoder reranker for second-stage precision.
bge-reranker-v2-m3 reads each (query, chunk) pair as a unit and assigns a
relevance score — much more accurate than bi-encoder cosine similarity,
especially for mixed-language Chinese+English content.
"""
from functools import lru_cache
from sentence_transformers import CrossEncoder
from ..config import settings


@lru_cache(maxsize=1)
def get_model() -> CrossEncoder:
    return CrossEncoder(
        settings.rerank_model,
        device=settings.embedding_device,
        cache_folder="./data/models",
    )


def rerank(query: str, candidates: list[str]) -> list[float]:
    """Return relevance score per candidate (higher = more relevant)."""
    if not candidates:
        return []
    model = get_model()
    pairs = [[query, c] for c in candidates]
    scores = model.predict(pairs, show_progress_bar=False)
    return scores.tolist()
