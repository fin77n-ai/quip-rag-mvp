from functools import lru_cache
from sentence_transformers import SentenceTransformer
from ..config import settings


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    return SentenceTransformer(
        settings.embedding_model,
        device=settings.embedding_device,
        cache_folder="./data/models",
    )


def encode(texts: list[str]) -> list[list[float]]:
    model = get_model()
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return embeddings.tolist()
