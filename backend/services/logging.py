"""Structured logging utilities for performance monitoring."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any


logger = logging.getLogger(__name__)


@contextmanager
def log_time(operation: str, threshold_ms: float = 100.0):
    """
    Context manager to log operation timing.

    Args:
        operation: Name of the operation
        threshold_ms: Only log if operation takes longer than this (ms)

    Example:
        with log_time("embedding generation"):
            embeddings = encode(texts)
    """
    start = time.time()
    try:
        yield
    finally:
        elapsed_ms = (time.time() - start) * 1000
        if elapsed_ms >= threshold_ms:
            logger.info(f"[PERF] {operation}: {elapsed_ms:.1f}ms")


def log_query_stats(question: str, candidate_count: int, group_count: int, elapsed_ms: float):
    """
    Log query execution statistics.

    Args:
        question: The query question
        candidate_count: Number of candidate chunks retrieved
        group_count: Number of similar evidence groups
        elapsed_ms: Total query time in milliseconds
    """
    logger.info(f"[QUERY] question='{question[:50]}...' candidates={candidate_count} groups={group_count} time={elapsed_ms:.1f}ms")


def log_embedding_cache_hit(text: str):
    """Log embedding cache hit (for debugging)."""
    logger.debug(f"[CACHE] Embedding cache hit for text: '{text[:30]}...'")


def log_error(context: str, error: Exception):
    """
    Log an error with context.

    Args:
        context: Description of what was being done
        error: The exception that occurred
    """
    logger.error(f"[ERROR] {context}: {type(error).__name__}: {str(error)}")
