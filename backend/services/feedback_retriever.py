from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from ..config import settings
from .duck_lance_store import duck
from . import embedder, duck_lance_store

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]{1,}")
_STOPWORDS = {
    "the", "and", "for", "that", "with", "this", "from", "into", "your", "have", "has",
    "had", "was", "were", "are", "but", "not", "too", "very", "more", "less", "just",
    "than", "then", "they", "them", "their", "there", "about", "issue", "video", "row",
    "sheet", "comment", "description", "implemented", "resolved", "please", "would", "could",
}


def _tokenize(text: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall((text or "").lower()) if token not in _STOPWORDS}


def _row_text(row: dict) -> str:
    cells = row.get("cells", {}) or {}
    if isinstance(cells, dict):
        return " | ".join(f"{key}: {value}" for key, value in cells.items() if value)
    return str(cells)


def _distilled_feedback_path() -> Path:
    return settings.tag_feedback_path.parent / "tag_feedback_distilled.json"


def _feedback_candidates(limit: int) -> list[dict]:
    rows = duck().execute(
        """
        SELECT
            tf.row_id,
            tf.predicted_category,
            tf.predicted_subcategory,
            tf.final_category,
            tf.final_subcategory,
            tf.final_tags,
            tf.action,
            tf.rationale,
            c.title,
            c.sheet,
            c.text,
            c.taxonomy_tags
        FROM taxonomy_feedback tf
        LEFT JOIN chunks c
          ON tf.row_id = c.doc_id || '::' || c.row_key
          OR tf.row_id = c.chunk_id
          OR tf.row_id = c.row_key
        WHERE tf.action IN ('approve', 'edit')
        ORDER BY tf.review_time DESC
        LIMIT ?
        """,
        [limit],
    ).fetchall()

    candidates = []
    for row in rows:
        candidates.append({
            "row_id": row[0],
            "predicted_category": row[1] or "",
            "predicted_subcategory": row[2] or "",
            "final_category": row[3] or "",
            "final_subcategory": row[4] or "",
            "final_tags": row[5] or "",
            "action": row[6] or "",
            "rationale": row[7] or "",
            "title": row[8] or "",
            "sheet": row[9] or "",
            "text": row[10] or "",
            "taxonomy_tags": row[11] or "",
        })
    return candidates


def get_recent_approved_feedback(limit: int = 5) -> str:
    candidates = _feedback_candidates(limit)
    if not candidates:
        return ""
    return _render_feedback_examples(candidates[:limit])


def get_relevant_feedback(
    batch_rows: list[dict],
    limit: int = 3,
    candidate_limit: int = 200,
) -> str:
    """
    Retrieve the most relevant human-reviewed taxonomy corrections for the
    current batch so they can be injected into the LLM prompt as few-shot hints.
    Now using LanceDB Vector Similarity!
    """
    # 1. Get all row_ids that have feedback
    feedback_rows = duck().execute("""
        SELECT tf.row_id, tf.action, tf.rationale, tf.predicted_category, tf.predicted_subcategory,
               tf.final_category, tf.final_subcategory, tf.final_tags
        FROM taxonomy_feedback tf
        WHERE tf.action IN ('approve', 'edit')
    """).fetchall()

    if not feedback_rows:
        return ""

    feedback_map = {}
    for r in feedback_rows:
        feedback_map[r[0]] = {
            "action": r[1],
            "rationale": r[2],
            "predicted_category": r[3],
            "predicted_subcategory": r[4],
            "final_category": r[5],
            "final_subcategory": r[6],
            "final_tags": r[7],
        }

    # 2. Embed the current batch's combined text
    batch_texts = [_row_text(row) for row in batch_rows]
    combined_query = " ".join(batch_texts)

    if not combined_query.strip():
        return ""

    query_embedding = embedder.encode([combined_query])[0]

    # 3. Vector search LanceDB for similar chunks
    # We ask for a lot of chunks (top 150) hoping some of them overlap with our feedback map
    search_results = duck_lance_store.search(query_embedding, top_k=150)

    if not search_results or not search_results["ids"] or not search_results["ids"][0]:
        return ""

    scored = []
    chunk_ids = search_results["ids"][0]
    chunk_docs = search_results["documents"][0]
    chunk_metas = search_results["metadatas"][0]
    distances = search_results["distances"][0]

    for c_id, c_doc, c_meta, c_dist in zip(chunk_ids, chunk_docs, chunk_metas, distances):
        # The feedback row_id might match chunk_id, or doc_id::row_key, or just row_key
        doc_id = c_meta.get("doc_id", "")
        row_key = c_meta.get("row_key", "")
        match_keys = [c_id, f"{doc_id}::{row_key}", row_key]

        fb = None
        for k in match_keys:
            if k in feedback_map:
                fb = feedback_map[k]
                break

        if fb:
            scored.append({
                "row_id": c_id,
                "title": c_meta.get("title", ""),
                "sheet": c_meta.get("sheet", ""),
                "text": c_doc,
                "action": fb["action"] or "",
                "rationale": fb["rationale"] or "",
                "predicted_category": fb["predicted_category"] or "",
                "predicted_subcategory": fb["predicted_subcategory"] or "",
                "final_category": fb["final_category"] or "",
                "final_subcategory": fb["final_subcategory"] or "",
                "final_tags": fb["final_tags"] or "",
                "taxonomy_tags": c_meta.get("taxonomy_tags", ""),
                "score": 1.0 - c_dist  # convert distance to similarity score
            })

    if not scored:
        # Fallback to Jaccard text overlap if no vector hits
        return _fallback_get_relevant_feedback(batch_texts, limit, candidate_limit)

    # Sort by similarity score
    selected = sorted(scored, key=lambda x: x["score"], reverse=True)[:limit]
    return _render_feedback_examples(selected)


def _fallback_get_relevant_feedback(batch_texts: list[str], limit: int, candidate_limit: int) -> str:
    candidates = _feedback_candidates(candidate_limit)
    if not candidates:
        return ""

    batch_tokens = [_tokenize(text) for text in batch_texts]
    aggregate_batch_tokens = Counter(token for tokens in batch_tokens for token in tokens)

    if not aggregate_batch_tokens:
        return ""

    scored = []
    for item in candidates:
        item_tokens = _tokenize(" ".join([
            item["text"],
            item["rationale"],
            item["predicted_category"],
            item["predicted_subcategory"],
            item["final_category"],
            item["final_subcategory"],
            item["final_tags"],
            item["taxonomy_tags"],
            item["title"],
            item["sheet"],
        ]))
        if not item_tokens:
            continue

        overlap = sum(aggregate_batch_tokens[token] for token in item_tokens if token in aggregate_batch_tokens)
        if overlap <= 0:
            continue

        best_jaccard = 0.0
        for row_tokens in batch_tokens:
            union = len(row_tokens | item_tokens)
            if union == 0:
                continue
            best_jaccard = max(best_jaccard, len(row_tokens & item_tokens) / union)

        score = overlap * 3 + best_jaccard
        scored.append((score, item))

    if not scored:
        return ""

    selected = [item for _score, item in sorted(scored, key=lambda pair: pair[0], reverse=True)[:limit]]
    return _render_feedback_examples(selected)


def get_relevant_distilled_rules(
    batch_rows: list[dict],
    limit: int = 4,
) -> str:
    """
    Retrieve the most relevant distilled review rules so they can be injected
    into the tagging prompt as compact policy guidance.
    """
    path = _distilled_feedback_path()
    if not path.exists():
        return ""

    try:
        distilled = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""

    rules = distilled.get("rules") or []
    examples = distilled.get("examples") or []
    if not rules and not examples:
        return ""

    batch_texts = [_row_text(row) for row in batch_rows]
    batch_tokens = [_tokenize(text) for text in batch_texts]
    aggregate_batch_tokens = Counter(token for tokens in batch_tokens for token in tokens)
    if not aggregate_batch_tokens:
        return ""

    scored_rules = []
    for idx, rule in enumerate(rules):
        rule_text = str(rule or "").strip()
        if not rule_text:
            continue
        rule_tokens = _tokenize(rule_text)
        if not rule_tokens:
            continue
        overlap = sum(aggregate_batch_tokens[token] for token in rule_tokens if token in aggregate_batch_tokens)
        if overlap <= 0:
            continue
        scored_rules.append((overlap, idx, rule_text))

    selected_rules = [rule for _score, _idx, rule in sorted(scored_rules, reverse=True)[:limit]]
    if not selected_rules and rules:
        selected_rules = [str(rule).strip() for rule in rules[: min(limit, len(rules))] if str(rule).strip()]

    scored_examples = []
    for example in examples:
        example_text = " ".join([
            str(example.get("from") or ""),
            str(example.get("to") or ""),
            " ".join(example.get("detail_tags") or []),
            str(example.get("note") or ""),
        ]).strip()
        if not example_text:
            continue
        example_tokens = _tokenize(example_text)
        if not example_tokens:
            continue
        overlap = sum(aggregate_batch_tokens[token] for token in example_tokens if token in aggregate_batch_tokens)
        if overlap <= 0:
            continue
        scored_examples.append((overlap, example))

    selected_examples = [example for _score, example in sorted(scored_examples, key=lambda pair: pair[0], reverse=True)[:2]]
    return _render_distilled_guidance(selected_rules, selected_examples)


def _render_feedback_examples(items: list[dict]) -> str:
    lines = [
        "Here are relevant human-reviewed taxonomy corrections for similar rows.",
        "Use them as guidance when classifying the next batch.",
        "",
    ]
    for item in items:
        # Simplify title to just the document prefix if available
        title = f"{item.get('sheet', '')}".strip()
        text_preview = (item.get("text") or "").replace("\n", " ").strip()
        if len(text_preview) > 100:
            text_preview = text_preview[:97] + "..."

        lines.append(f"- Example: {text_preview}")
        if item.get("final_category"):
            lines.append(f"  * Category: {item.get('final_category')}")
        if item.get("final_tags"):
            lines.append(f"  * Tags: {item['final_tags']}")
        if item.get("rationale"):
            lines.append(f"  * Rationale: {item['rationale']}")
        lines.append("")

    return "\n".join(lines).strip()


def _render_distilled_guidance(rules: list[str], examples: list[dict]) -> str:
    if not rules and not examples:
        return ""

    lines = [
        "Here are distilled review rules derived from repeated human corrections.",
        "Treat them as compact policy guidance, not as absolute truth.",
        "",
    ]
    for rule in rules:
        lines.append(f"- Rule: {rule}")
    if rules and examples:
        lines.append("")
    for example in examples:
        detail_tags = ", ".join(example.get("detail_tags") or [])
        lines.append(
            f"- Example: {example.get('from') or 'unclassified'} -> {example.get('to') or 'unclassified'}"
        )
        if detail_tags:
            lines.append(f"  * Detail Tags: {detail_tags}")
        if example.get("note"):
            lines.append(f"  * Note: {example['note']}")
    return "\n".join(lines).strip()
