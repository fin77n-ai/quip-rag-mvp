"""Tests for reranker service."""

import pytest
from backend.services import reranker


def test_reranker_basic():
    """Test basic reranking functionality."""
    query = "iPhone update issue"
    candidates = [
        "How to update your iPhone to the latest version",
        "Battery drain after update",
        "Random unrelated text about cooking"
    ]

    scores = reranker.rerank(query, candidates)

    assert len(scores) == len(candidates)
    assert all(isinstance(score, float) for score in scores)
    # First candidate should be most relevant
    assert scores[0] > scores[2]


def test_reranker_empty():
    """Test reranker with empty candidates."""
    scores = reranker.rerank("test query", [])
    assert scores == []


def test_reranker_single():
    """Test reranker with single candidate."""
    scores = reranker.rerank("test", ["single candidate"])
    assert len(scores) == 1
    assert isinstance(scores[0], float)
