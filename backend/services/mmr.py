"""
Maximal Marginal Relevance (MMR) — diversity-aware re-selection.

Picks top-k items balancing two objectives:
  1. High relevance to the query
  2. Low similarity to already-selected items

Score: mmr = λ * relevance - (1-λ) * max_similarity_to_selected
"""
import numpy as np


def select(
    relevance_scores: list[float],
    embeddings: list[list[float]],
    top_k: int,
    lambda_: float = 0.7,
) -> list[int]:
    """Return indices of the top_k items chosen by MMR, in selection order."""
    n = len(relevance_scores)
    if n == 0:
        return []
    if top_k >= n:
        # Nothing to filter — return indices sorted by relevance
        return sorted(range(n), key=lambda i: relevance_scores[i], reverse=True)

    embs = np.array(embeddings, dtype=np.float32)
    # Normalize so dot product = cosine similarity
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    embs = embs / norms

    rels = np.array(relevance_scores, dtype=np.float32)

    # Normalize relevance to [0, 1] for stable mixing with cosine sim (also in [-1, 1])
    rmin, rmax = float(rels.min()), float(rels.max())
    if rmax > rmin:
        rels_n = (rels - rmin) / (rmax - rmin)
    else:
        rels_n = np.ones_like(rels)

    selected: list[int] = []
    remaining = set(range(n))

    while len(selected) < top_k and remaining:
        if not selected:
            # First pick: pure relevance
            best = max(remaining, key=lambda i: rels_n[i])
        else:
            sel_embs = embs[selected]
            best, best_score = -1, -np.inf
            for i in remaining:
                sims = sel_embs @ embs[i]   # cosine similarity to each selected
                max_sim = float(sims.max())
                score = lambda_ * float(rels_n[i]) - (1 - lambda_) * max_sim
                if score > best_score:
                    best_score = score
                    best = i
        selected.append(best)
        remaining.remove(best)

    return selected
