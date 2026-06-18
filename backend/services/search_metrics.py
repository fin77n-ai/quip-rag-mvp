"""Search precision evaluation metrics."""

from __future__ import annotations

from typing import List, Set


def precision_at_k(relevant_ids: Set[str], retrieved_ids: List[str], k: int) -> float:
    """
    Calculate Precision@K.

    Args:
        relevant_ids: Set of relevant document IDs (ground truth)
        retrieved_ids: List of retrieved document IDs (ranked by relevance)
        k: Number of top results to consider

    Returns:
        Precision@K score (0.0 to 1.0)
    """
    if k <= 0 or not retrieved_ids:
        return 0.0

    top_k = retrieved_ids[:k]
    relevant_retrieved = sum(1 for doc_id in top_k if doc_id in relevant_ids)

    return relevant_retrieved / k


def recall_at_k(relevant_ids: Set[str], retrieved_ids: List[str], k: int) -> float:
    """
    Calculate Recall@K.

    Args:
        relevant_ids: Set of relevant document IDs (ground truth)
        retrieved_ids: List of retrieved document IDs (ranked by relevance)
        k: Number of top results to consider

    Returns:
        Recall@K score (0.0 to 1.0)
    """
    if not relevant_ids or k <= 0:
        return 0.0

    top_k = retrieved_ids[:k]
    relevant_retrieved = sum(1 for doc_id in top_k if doc_id in relevant_ids)

    return relevant_retrieved / len(relevant_ids)


def mrr(relevant_ids: Set[str], retrieved_ids: List[str]) -> float:
    """
    Calculate Mean Reciprocal Rank (MRR).

    Args:
        relevant_ids: Set of relevant document IDs (ground truth)
        retrieved_ids: List of retrieved document IDs (ranked by relevance)

    Returns:
        MRR score (0.0 to 1.0)
    """
    if not retrieved_ids or not relevant_ids:
        return 0.0

    for rank, doc_id in enumerate(retrieved_ids, start=1):
        if doc_id in relevant_ids:
            return 1.0 / rank

    return 0.0


def ndcg_at_k(relevant_ids: Set[str], retrieved_ids: List[str], k: int) -> float:
    """
    Calculate Normalized Discounted Cumulative Gain (NDCG@K).

    Simplified binary relevance version (relevant=1, non-relevant=0).

    Args:
        relevant_ids: Set of relevant document IDs (ground truth)
        retrieved_ids: List of retrieved document IDs (ranked by relevance)
        k: Number of top results to consider

    Returns:
        NDCG@K score (0.0 to 1.0)
    """
    if k <= 0 or not retrieved_ids or not relevant_ids:
        return 0.0

    import math

    # DCG: sum of (relevance / log2(rank+1))
    dcg = 0.0
    for rank, doc_id in enumerate(retrieved_ids[:k], start=1):
        relevance = 1.0 if doc_id in relevant_ids else 0.0
        dcg += relevance / math.log2(rank + 1)

    # IDCG: best possible DCG (all relevant docs at top)
    ideal_ranking = [1.0] * min(len(relevant_ids), k)
    idcg = sum(rel / math.log2(rank + 1) for rank, rel in enumerate(ideal_ranking, start=1))

    if idcg == 0.0:
        return 0.0

    return dcg / idcg


def evaluate_query(
    relevant_ids: Set[str],
    retrieved_ids: List[str],
    k_values: List[int] = [1, 3, 5, 10],
) -> dict:
    """
    Evaluate a single query with multiple metrics.

    Args:
        relevant_ids: Set of relevant document IDs (ground truth)
        retrieved_ids: List of retrieved document IDs (ranked by relevance)
        k_values: List of K values to evaluate

    Returns:
        Dict with metrics for each K value
    """
    results = {
        "mrr": mrr(relevant_ids, retrieved_ids),
        "precision": {},
        "recall": {},
        "ndcg": {},
    }

    for k in k_values:
        results["precision"][f"@{k}"] = precision_at_k(relevant_ids, retrieved_ids, k)
        results["recall"][f"@{k}"] = recall_at_k(relevant_ids, retrieved_ids, k)
        results["ndcg"][f"@{k}"] = ndcg_at_k(relevant_ids, retrieved_ids, k)

    return results


def evaluate_queries(test_cases: List[dict], k_values: List[int] = [1, 3, 5, 10]) -> dict:
    """
    Evaluate multiple queries and compute average metrics.

    Args:
        test_cases: List of dicts with 'relevant_ids' and 'retrieved_ids' keys
        k_values: List of K values to evaluate

    Returns:
        Dict with averaged metrics across all queries

    Example:
        test_cases = [
            {
                "query": "iPhone update issue",
                "relevant_ids": {"chunk_1", "chunk_2"},
                "retrieved_ids": ["chunk_1", "chunk_3", "chunk_2"],
            }
        ]
        results = evaluate_queries(test_cases)
    """
    all_results = [
        evaluate_query(case["relevant_ids"], case["retrieved_ids"], k_values)
        for case in test_cases
    ]

    # Average across all queries
    avg_results = {
        "mrr": sum(r["mrr"] for r in all_results) / len(all_results),
        "precision": {},
        "recall": {},
        "ndcg": {},
        "num_queries": len(test_cases),
    }

    for k in k_values:
        key = f"@{k}"
        avg_results["precision"][key] = sum(r["precision"][key] for r in all_results) / len(all_results)
        avg_results["recall"][key] = sum(r["recall"][key] for r in all_results) / len(all_results)
        avg_results["ndcg"][key] = sum(r["ndcg"][key] for r in all_results) / len(all_results)

    return avg_results
