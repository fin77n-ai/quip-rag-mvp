"""Custom exceptions and error handling utilities."""

from __future__ import annotations


class QuipRagError(Exception):
    """Base exception for all quip-rag errors."""
    pass


class VectorStoreError(QuipRagError):
    """Errors related to vector store operations."""
    pass


class EmbeddingError(QuipRagError):
    """Errors during embedding generation."""
    pass


class ParsingError(QuipRagError):
    """Errors parsing Quip documents."""
    pass


class QueryError(QuipRagError):
    """Errors during query execution."""
    pass


class ValidationError(QuipRagError):
    """Data validation errors."""
    pass


class ConfigurationError(QuipRagError):
    """Configuration or setup errors."""
    pass


def format_error_message(error: Exception, context: str = "") -> str:
    """
    Format an error message with context.

    Args:
        error: The exception that occurred
        context: Additional context about where/why the error happened

    Returns:
        Formatted error string
    """
    error_type = type(error).__name__
    error_msg = str(error)

    if context:
        return f"{context}: {error_type}: {error_msg}"
    return f"{error_type}: {error_msg}"
