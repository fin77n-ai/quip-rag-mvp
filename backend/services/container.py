"""Dependency injection container for service management."""

from __future__ import annotations

from functools import lru_cache
from typing import Protocol

from sentence_transformers import SentenceTransformer, CrossEncoder


class EmbedderProtocol(Protocol):
    """Protocol for embedding service."""
    def encode(self, texts: list[str], batch_size: int = 32, show_progress: bool = False) -> list[list[float]]: ...


class RerankerProtocol(Protocol):
    """Protocol for reranking service."""
    def rerank(self, query: str, candidates: list[str]) -> list[float]: ...


class VectorStoreProtocol(Protocol):
    """Protocol for vector store service."""
    def search(self, query_embedding: list[float], top_k: int, where: dict | None = None) -> dict: ...
    def upsert_chunks(self, chunks: list[dict], category: str) -> None: ...


class ServiceContainer:
    """
    Simple dependency injection container.

    Usage:
        container = ServiceContainer()
        embedder = container.get_embedder()
        vector_store = container.get_vector_store()
    """

    def __init__(self):
        self._embedder_model: SentenceTransformer | None = None
        self._reranker_model: CrossEncoder | None = None

    @lru_cache(maxsize=1)
    def get_embedder_model(self) -> SentenceTransformer:
        """Get or create embedding model (singleton)."""
        if self._embedder_model is None:
            from ..config import settings
            from .errors import EmbeddingError
            try:
                self._embedder_model = SentenceTransformer(
                    settings.embedding_model,
                    device=settings.embedding_device,
                    cache_folder="./data/models",
                )
            except Exception as e:
                raise EmbeddingError(f"Failed to load embedding model: {e}") from e
        return self._embedder_model

    @lru_cache(maxsize=1)
    def get_reranker_model(self) -> CrossEncoder:
        """Get or create reranker model (singleton)."""
        if self._reranker_model is None:
            from ..config import settings
            self._reranker_model = CrossEncoder(
                settings.rerank_model,
                device=settings.embedding_device,
                cache_folder="./data/models",
            )
        return self._reranker_model

# Global container instance
_container = ServiceContainer()


def get_container() -> ServiceContainer:
    """Get the global service container."""
    return _container
