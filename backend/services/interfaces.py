"""Abstract interfaces for core services."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol


class VectorStoreInterface(ABC):
    """Interface for vector store operations."""

    @abstractmethod
    def search(
        self,
        query_embedding: list[float],
        top_k: int,
        where: dict | None = None,
        include_embeddings: bool = False,
    ) -> dict:
        """Search for similar vectors."""
        pass

    @abstractmethod
    def upsert_chunks(self, chunks: list[dict], category: str) -> None:
        """Insert or update chunks."""
        pass

    @abstractmethod
    def delete_doc(self, doc_id: str) -> None:
        """Delete all chunks for a document."""
        pass

    @abstractmethod
    def get_chunks(self, doc_id: str) -> list[dict]:
        """Get all chunks for a document."""
        pass

    @abstractmethod
    def stats(self) -> dict:
        """Get vector store statistics."""
        pass


class EmbedderInterface(ABC):
    """Interface for embedding generation."""

    @abstractmethod
    def encode(
        self,
        texts: list[str],
        batch_size: int = 32,
        show_progress: bool = False,
    ) -> list[list[float]]:
        """Encode texts to embeddings."""
        pass


class RerankerInterface(ABC):
    """Interface for reranking."""

    @abstractmethod
    def rerank(self, query: str, candidates: list[str]) -> list[float]:
        """Rerank candidates by relevance to query."""
        pass


class TagsStoreInterface(ABC):
    """Interface for tag storage."""

    @abstractmethod
    def load(self, doc_id: str):
        """Load tags for a document."""
        pass

    @abstractmethod
    def save(self, tags) -> None:
        """Save tags for a document."""
        pass

    @abstractmethod
    def set_row(self, doc_id: str, key: str, tag) -> None:
        """Set tag for a specific row."""
        pass


class LLMClientInterface(ABC):
    """Interface for LLM client."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        """Generate text from LLM."""
        pass


# Protocol versions (for type checking without inheritance)

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
    def delete_doc(self, doc_id: str) -> None: ...
    def get_chunks(self, doc_id: str) -> list[dict]: ...
    def stats(self) -> dict: ...
