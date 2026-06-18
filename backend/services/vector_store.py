from __future__ import annotations

from collections import Counter
import json

from ..config import settings
from ..models.tags import RowTag
from . import chunker, duck_lance_store, embedder, quip_parser, tags_store

UNTAGGED = "(untagged)"


def get_collection():
    # Deprecated: returning duck_lance_store table if needed
    pass


def upsert_chunks(chunks: list[dict], category: str) -> None:
    if not chunks:
        return
    for chunk in chunks:
        chunk["metadata"]["category"] = category
    embeddings = embedder.encode([c["embed_text"] for c in chunks])
    duck_lance_store.upsert_chunks(chunks, embeddings)


def delete_doc(doc_id: str) -> None:
    duck_lance_store.delete_doc(doc_id)


def search(query_embedding: list[float], top_k: int, where: dict | None = None,
           include_embeddings: bool = False, ids: list[str] | None = None) -> dict:
    res = duck_lance_store.search(query_embedding, top_k, where, include_embeddings, ids)
    return res or {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}


def list_docs(category: str | None = None, sprint: str | None = None) -> list[dict]:
    return duck_lance_store.list_docs(category, sprint) or []


def get_chunks(doc_id: str) -> list[dict]:
    return duck_lance_store.get_chunks(doc_id) or []


def update_doc_metadata(doc_id: str, category: str | None = None, sprint: str | None = None) -> int:
    duck_lance_store.update_doc_metadata(doc_id, category, sprint)
    return 1 # Cannot get updated count easily, return 1 as success


def sync_row_tag(doc_id: str, row_key: str, tag: RowTag) -> int:
    duck_lance_store.update_row_tag(doc_id, row_key, tag)
    return 1


def get_chunk_ids(where: dict | None = None, tags: list[str] | None = None) -> list[str]:
    return duck_lance_store.get_chunk_ids(where, tags)


def list_memories(
    category: str | None = None,
    sprint: str | None = None,
    tag: str | None = None,
    doc_id: str | None = None,
    q: str | None = None,
    limit: int = 200,
    include_noise: bool = False,
) -> list[dict]:
    return duck_lance_store.list_memories(
        category=category,
        sprint=sprint,
        tag=tag,
        doc_id=doc_id,
        q=q,
        limit=limit,
        include_noise=include_noise
    )


def stats() -> dict:
    return duck_lance_store.stats() or {}


def stats_breakdown(category: str | None = None, sprint: str | None = None, tag: str | None = None) -> dict:
    return duck_lance_store.stats_breakdown(category, sprint, tag)


def list_sprints() -> list[str]:
    return duck_lance_store.list_sprints()


def list_review_rows(limit: int = 200) -> list[dict]:
    return _list_tagged_rows(limit=limit, mode="review")


def list_noise_rows(limit: int = 200) -> list[dict]:
    return _list_tagged_rows(limit=limit, mode="noise")


def _list_tagged_rows(limit: int = 200, mode: str = "review") -> list[dict]:
    rows = []
    doc_meta = {doc["doc_id"]: doc for doc in list_docs()}

    import logging
    logger = logging.getLogger(__name__)

    # Build a map of doc_id -> all chunks for context lookup
    doc_chunks_map: dict[str, list[tuple[str, str, int, str]]] = {}

    # Get all from duckdb
    # We use the existing connection from duck_lance_store to avoid configuration mismatch errors
    from . import duck_lance_store
    import time

    # Simple retry logic for DuckDB connection
    max_retries = 3
    results = []

    for attempt in range(max_retries):
        try:
            # Check if there's any data first to avoid long queries if empty
            conn = duck_lance_store.duck()
            try:
                results = conn.execute("SELECT doc_id, row_key, sheet, row_index, text FROM chunks").fetchall()
            except Exception as e:
                if "Table with name chunks does not exist" in str(e):
                    results = []
                else:
                    raise e
            break  # Success
        except Exception as e:
            logger.warning(f"DuckDB access attempt {attempt+1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(1)  # Wait longer before retry
            else:
                logger.warning(f"Error reading from duckdb for review queue: {e}")
                break

    for doc_id, row_key, sheet, row_index, text in results:
        if doc_id not in doc_chunks_map:
            doc_chunks_map[doc_id] = []
        doc_chunks_map[doc_id].append((row_key, sheet, row_index, text or ""))

    for doc_tags in tags_store.iter_all():
        meta = doc_meta.get(doc_tags.doc_id, {})
        doc_chunks = doc_chunks_map.get(doc_tags.doc_id, [])
        stale_row_keys: list[str] = []

        for row_key, row in doc_tags.rows.items():
            if mode == "review":
                if not row.review_required or row.excluded or row.is_noise:
                    continue
            elif mode == "noise":
                if not row.is_noise and not row.excluded:
                    continue

            # Find current row text and context
            text_content = ""
            context_before = []
            context_after = []
            current_sheet = ""
            current_index = 0

            # Find current row
            for key, sheet, idx, text in doc_chunks:
                if key == row_key:
                    text_content = text
                    current_sheet = sheet
                    current_index = idx
                    break

            if not text_content:
                stale_row_keys.append(row_key)
                continue

            # Get context: previous and next rows from same sheet
            for key, sheet, idx, text in doc_chunks:
                if sheet == current_sheet and text:
                    if idx < current_index and len(context_before) < 2:
                        context_before.append({"row_key": key, "text": text[:200]})
                    elif idx > current_index and len(context_after) < 2:
                        context_after.append({"row_key": key, "text": text[:200]})

            # Sort context_before in reverse order (most recent first)
            context_before.sort(key=lambda x: x["row_key"], reverse=True)

            rows.append({
                "doc_id": doc_tags.doc_id,
                "row_key": row_key,
                "title": meta.get("title", doc_tags.doc_id),
                "code": meta.get("code", ""),
                "sprint": meta.get("sprint", ""),
                "category": meta.get("category", ""),
                "category_tag": row.category_tag or row.taxonomy_category,
                "detail_tags": row.detail_tags or row.taxonomy_tags,
                "confidence": row.confidence or row.taxonomy_confidence,
                "review_reason": row.review_reason,
                "rationale": row.rationale or row.taxonomy_rationale,
                "tags": row.tags,
                "is_noise": row.is_noise or row.excluded,
                "text": text_content,
                "context_before": context_before,
                "context_after": context_after,
            })
        if stale_row_keys:
            try:
                tags_store.delete_rows(doc_tags.doc_id, stale_row_keys)
            except Exception as e:
                logger.warning(f"Failed to clean stale row tags for {doc_tags.doc_id}: {e}")
    rows.sort(key=lambda item: (item["confidence"], item["doc_id"], item["row_key"]))
    return rows[:limit]


def delete_chunk_by_row(doc_id: str, row_key: str) -> int:
    try:
        import duckdb
        conn = duckdb.connect(str(settings.duckdb_path), read_only=True)
        results = conn.execute("SELECT chunk_id FROM chunks WHERE doc_id = ? AND row_key = ?", [doc_id, row_key]).fetchall()
        conn.close()
        for res in results:
            duck_lance_store.delete_chunk(res[0])
        return len(results)
    except Exception:
        return 0


def restore_chunk_by_row(doc_id: str, row_key: str) -> int:
    source_path = settings.quip_dir / f"{doc_id}.json"
    if not source_path.exists():
        return 0

    raw_doc = json.loads(source_path.read_text(encoding="utf-8"))
    parsed = quip_parser.parse_dict(raw_doc)
    chunks = [
        chunk
        for chunk in chunker.chunk_doc(parsed)
        if chunk.get("metadata", {}).get("row_key") == row_key
    ]
    if not chunks:
        return 0

    category = parsed.prefix or "VSD"
    upsert_chunks(chunks, category=category)
    return len(chunks)
