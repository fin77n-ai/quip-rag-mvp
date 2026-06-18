"""Tests for search metrics."""

import pytest
from backend.services.search_metrics import (
    precision_at_k,
    recall_at_k,
    mrr,
    ndcg_at_k,
    evaluate_query,
    evaluate_queries,
)


def test_precision_at_k():
    """Test Precision@K calculation."""
    relevant = {"doc1", "doc2", "doc3"}
    retrieved = ["doc1", "doc4", "doc2", "doc5"]

    assert precision_at_k(relevant, retrieved, 1) == 1.0  # 1/1
    assert precision_at_k(relevant, retrieved, 2) == 0.5  # 1/2
    assert precision_at_k(relevant, retrieved, 3) == pytest.approx(0.666, rel=0.01)  # 2/3
    assert precision_at_k(relevant, retrieved, 4) == 0.5  # 2/4


def test_recall_at_k():
    """Test Recall@K calculation."""
    relevant = {"doc1", "doc2", "doc3"}
    retrieved = ["doc1", "doc4", "doc2", "doc5"]

    assert recall_at_k(relevant, retrieved, 1) == pytest.approx(0.333, rel=0.01)  # 1/3
    assert recall_at_k(relevant, retrieved, 2) == pytest.approx(0.333, rel=0.01)  # 1/3
    assert recall_at_k(relevant, retrieved, 3) == pytest.approx(0.666, rel=0.01)  # 2/3
    assert recall_at_k(relevant, retrieved, 4) == pytest.approx(0.666, rel=0.01)  # 2/3


def test_mrr():
    """Test Mean Reciprocal Rank calculation."""
    relevant = {"doc1", "doc2"}

    # First result is relevant
    assert mrr(relevant, ["doc1", "doc3", "doc2"]) == 1.0

    # Second result is relevant
    assert mrr(relevant, ["doc3", "doc1", "doc2"]) == 0.5

    # Third result is relevant
    assert mrr(relevant, ["doc3", "doc4", "doc2"]) == pytest.approx(0.333, rel=0.01)

    # No relevant results
    assert mrr(relevant, ["doc3", "doc4", "doc5"]) == 0.0


def test_ndcg_at_k():
    """Test NDCG@K calculation."""
    relevant = {"doc1", "doc2", "doc3"}

    # Perfect ranking
    perfect = ["doc1", "doc2", "doc3", "doc4"]
    assert ndcg_at_k(relevant, perfect, 3) == 1.0

    # Some relevant at top
    mixed = ["doc1", "doc4", "doc2", "doc3"]
    assert 0.0 < ndcg_at_k(relevant, mixed, 3) < 1.0

    # No relevant results
    bad = ["doc4", "doc5", "doc6"]
    assert ndcg_at_k(relevant, bad, 3) == 0.0


def test_evaluate_query():
    """Test full query evaluation."""
    relevant = {"doc1", "doc2"}
    retrieved = ["doc1", "doc3", "doc2"]

    results = evaluate_query(relevant, retrieved, k_values=[1, 3])

    assert "mrr" in results
    assert "precision" in results
    assert "@1" in results["precision"]
    assert "@3" in results["precision"]
    assert results["mrr"] == 1.0  # First result is relevant


def test_evaluate_queries():
    """Test batch query evaluation."""
    test_cases = [
        {
            "query": "test1",
            "relevant_ids": {"doc1", "doc2"},
            "retrieved_ids": ["doc1", "doc2", "doc3"],
        },
        {
            "query": "test2",
            "relevant_ids": {"doc3"},
            "retrieved_ids": ["doc3", "doc1", "doc2"],
        },
    ]

    results = evaluate_queries(test_cases, k_values=[1, 3])

    assert results["num_queries"] == 2
    assert "mrr" in results
    assert "precision" in results
    assert "@1" in results["precision"]
    assert 0.0 <= results["mrr"] <= 1.0
