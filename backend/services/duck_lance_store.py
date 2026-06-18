"""Experimental DuckDB + Lance mirror for analysis-first sprint comparison."""

from __future__ import annotations

from collections import Counter
from functools import lru_cache
from typing import Iterable

import duckdb
import lancedb

from ..config import settings
from ..models.tags import RowTag
from . import embedder, issue_fields
from .issue_normalizer import extract_issue_text, memory_example, normalize_issue_text, split_tags


TABLE_NAME = "chunks"
UNTAGGED = "(untagged)"
CHUNK_SELECT_COLUMNS = (
    "chunk_id", "doc_id", "title", "category", "code", "sprint", "language", "video_code",
    "sheet", "row_index", "row_key", "tags", "is_issue", "issue_summary", "issue_type",
    "owner", "status", "issue_source", "is_noise", "taxonomy_category", "taxonomy_subcategory", "taxonomy_tags",
    "taxonomy_confidence", "taxonomy_rationale", "retake_explicit", "retake_terms", "issue_key",
    "text", "word_count", "processed_at",
)


def is_enabled() -> bool:
    return bool(settings.duck_lance_enabled)


@lru_cache(maxsize=1)
def duck() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(str(settings.duckdb_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id TEXT PRIMARY KEY,
            doc_id TEXT,
            title TEXT,
            category TEXT,
            code TEXT,
            sprint TEXT,
            language TEXT,
            video_code TEXT,
            sheet TEXT,
            row_index INTEGER,
            row_key TEXT,
            tags TEXT,
            is_issue TEXT,
            issue_summary TEXT,
            issue_type TEXT,
            owner TEXT,
            status TEXT,
            issue_source TEXT,
            is_noise TEXT,
            taxonomy_category TEXT,
            taxonomy_subcategory TEXT,
            taxonomy_tags TEXT,
            taxonomy_confidence DOUBLE,
            taxonomy_rationale TEXT,
            retake_explicit TEXT,
            retake_terms TEXT,
            issue_key TEXT,
            text TEXT,
            word_count INTEGER,
            processed_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS taxonomy_predictions (
            row_id TEXT PRIMARY KEY,
            predicted_category TEXT,
            predicted_subcategory TEXT,
            predicted_tags TEXT,
            confidence DOUBLE,
            rationale TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS taxonomy_feedback (
            row_id TEXT,
            predicted_category TEXT,
            predicted_subcategory TEXT,
            predicted_tags TEXT,
            final_category TEXT,
            final_subcategory TEXT,
            final_tags TEXT,
            action TEXT,
            reviewer TEXT,
            review_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            rationale TEXT,
            UNIQUE(row_id)
        )
    """)
    for column, col_type in (
        ("language", "TEXT"),
        ("video_code", "TEXT"),
        ("taxonomy_category", "TEXT"),
        ("taxonomy_subcategory", "TEXT"),
        ("taxonomy_tags", "TEXT"),
        ("taxonomy_confidence", "DOUBLE"),
        ("taxonomy_rationale", "TEXT"),
        ("retake_explicit", "TEXT"),
        ("retake_terms", "TEXT"),
        ("is_noise", "TEXT"),
        ("issue_source", "TEXT"),
        ("processed_at", "TEXT"),
    ):
        conn.execute(f"ALTER TABLE chunks ADD COLUMN IF NOT EXISTS {column} {col_type}")

    return conn


@lru_cache(maxsize=1)
def lance_db():
    return lancedb.connect(str(settings.lance_dir))


def _table_names() -> list[str]:
    tables = lance_db().list_tables()
    return list(getattr(tables, "tables", tables))


def _lance_table():
    db = lance_db()
    if TABLE_NAME not in _table_names():
        return None
    return db.open_table(TABLE_NAME)


def _lance_columns(table) -> set[str]:
    try:
        schema = table.schema
        names = getattr(schema, "names", None)
        if names:
            return set(names)
        return {field.name for field in schema}
    except Exception:
        return set()


def _filter_lance_values(table, values: dict) -> dict:
    columns = _lance_columns(table)
    if not columns:
        return values
    return {key: value for key, value in values.items() if key in columns}


def _quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _in_clause(values: Iterable[str]) -> str:
    return "(" + ", ".join(_quote(value) for value in values) + ")"


def reset() -> None:
    duck().execute("DROP TABLE IF EXISTS chunks")
    duck.cache_clear()
    if TABLE_NAME in _table_names():
        lance_db().drop_table(TABLE_NAME)


def _meta_value(meta: dict, key: str, default: str = "") -> str:
    value = meta.get(key, default)
    return "" if value is None else str(value)


def _chunk_select_list(conn) -> str:
    available = {row[1] for row in conn.execute("PRAGMA table_info('chunks')").fetchall()}
    return ", ".join(
        column if column in available else f"NULL AS {column}"
        for column in CHUNK_SELECT_COLUMNS
    )


def _issue_key(text: str, meta: dict) -> str:
    issue_type = _meta_value(meta, "issue_type").strip().lower()
    if issue_type:
        return f"type:{issue_type}"
    summary = _meta_value(meta, "issue_summary").strip()
    if summary:
        return normalize_issue_text(summary)
    return normalize_issue_text(text)


def _duck_row(chunk: dict, embedding: list[float] | None = None) -> tuple:
    meta = chunk["metadata"]
    text = chunk["text"]
    return (
        chunk["id"],
        _meta_value(meta, "doc_id"),
        _meta_value(meta, "title"),
        _meta_value(meta, "category"),
        _meta_value(meta, "code"),
        _meta_value(meta, "sprint"),
        _meta_value(meta, "language"),
        _meta_value(meta, "video_code"),
        _meta_value(meta, "sheet"),
        int(meta.get("row_index") or 0),
        _meta_value(meta, "row_key"),
        _meta_value(meta, "tags"),
        _meta_value(meta, "is_issue"),
        _meta_value(meta, "issue_summary"),
        _meta_value(meta, "issue_type"),
        _meta_value(meta, "owner"),
        _meta_value(meta, "status"),
        _meta_value(meta, "issue_source"),
        _meta_value(meta, "is_noise"),
        _meta_value(meta, "taxonomy_category"),
        _meta_value(meta, "taxonomy_subcategory"),
        _meta_value(meta, "taxonomy_tags"),
        float(meta.get("taxonomy_confidence") or 0.0),
        _meta_value(meta, "taxonomy_rationale"),
        _meta_value(meta, "retake_explicit"),
        _meta_value(meta, "retake_terms"),
        _issue_key(text, meta),
        text,
        int(meta.get("word_count") or len(text.split())),
        _meta_value(meta, "processed_at"),
    )


def _lance_row(chunk: dict, embedding: list[float]) -> dict:
    meta = chunk["metadata"]
    return {
        "chunk_id": chunk["id"],
        "vector": [float(v) for v in embedding],
        "text": chunk["text"],
        "doc_id": _meta_value(meta, "doc_id"),
        "title": _meta_value(meta, "title"),
        "category": _meta_value(meta, "category"),
        "code": _meta_value(meta, "code"),
        "sprint": _meta_value(meta, "sprint"),
        "sheet": _meta_value(meta, "sheet"),
        "row_index": int(meta.get("row_index") or 0),
        "row_key": _meta_value(meta, "row_key"),
        "tags": _meta_value(meta, "tags"),
        "is_issue": _meta_value(meta, "is_issue"),
        "issue_summary": _meta_value(meta, "issue_summary"),
        "issue_type": _meta_value(meta, "issue_type"),
        "owner": _meta_value(meta, "owner"),
        "status": _meta_value(meta, "status"),
        "issue_source": _meta_value(meta, "issue_source"),
        "is_noise": _meta_value(meta, "is_noise"),
        "taxonomy_category": _meta_value(meta, "taxonomy_category"),
        "taxonomy_subcategory": _meta_value(meta, "taxonomy_subcategory"),
        "taxonomy_tags": _meta_value(meta, "taxonomy_tags"),
        "taxonomy_confidence": float(meta.get("taxonomy_confidence") or 0.0),
        "taxonomy_rationale": _meta_value(meta, "taxonomy_rationale"),
        "retake_explicit": _meta_value(meta, "retake_explicit"),
        "retake_terms": _meta_value(meta, "retake_terms"),
        "issue_key": _issue_key(chunk["text"], meta),
        "processed_at": _meta_value(meta, "processed_at"),
    }


def upsert_chunks(chunks: list[dict], embeddings: list[list[float]]) -> None:
    if not is_enabled() or not chunks:
        return

    ids = [chunk["id"] for chunk in chunks]
    conn = duck()
    conn.executemany("DELETE FROM chunks WHERE chunk_id = ?", [(chunk_id,) for chunk_id in ids])
    conn.executemany(
        """
        INSERT INTO chunks (
            chunk_id, doc_id, title, category, code, sprint, language, video_code, sheet, row_index, row_key,
            tags, is_issue, issue_summary, issue_type, owner, status, issue_source,
            is_noise, taxonomy_category, taxonomy_subcategory, taxonomy_tags, taxonomy_confidence, taxonomy_rationale,
            retake_explicit, retake_terms, issue_key, text, word_count, processed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [_duck_row(chunk) for chunk in chunks],
    )

    db = lance_db()
    if TABLE_NAME not in _table_names():
        rows = [_lance_row(chunk, embedding) for chunk, embedding in zip(chunks, embeddings)]
        db.create_table(TABLE_NAME, data=rows)
        return

    table = db.open_table(TABLE_NAME)
    rows = [
        _filter_lance_values(table, _lance_row(chunk, embedding))
        for chunk, embedding in zip(chunks, embeddings)
    ]
    if ids:
        table.delete(f"chunk_id IN {_in_clause(ids)}")
    table.add(rows)


def delete_doc(doc_id: str) -> None:
    if not is_enabled():
        return

    # Delete related taxonomy predictions (row_id starts with doc_id::)
    duck().execute("DELETE FROM taxonomy_predictions WHERE row_id LIKE ?", [f"{doc_id}::%"])
    duck().execute("DELETE FROM taxonomy_feedback WHERE row_id LIKE ?", [f"{doc_id}::%"])

    duck().execute("DELETE FROM chunks WHERE doc_id = ?", [doc_id])
    table = _lance_table()
    if table is not None:
        table.delete(f"doc_id = {_quote(doc_id)}")


def update_row_tag(doc_id: str, row_key: str, tag: RowTag) -> None:
    if not is_enabled():
        return
    updates = {"tags": ",".join(tag.tags)}

    fields = issue_fields.fields_from_row_tag(tag)
    for field_name in issue_fields.ISSUE_FIELD_NAMES:
        updates[field_name] = fields.get(field_name, "")
    updates.update({
        "issue_source": tag.issue_source,
        "taxonomy_category": tag.taxonomy_category,
        "taxonomy_subcategory": tag.taxonomy_subcategory,
        "taxonomy_tags": ",".join(tag.taxonomy_tags),
        "taxonomy_confidence": float(tag.taxonomy_confidence or 0.0),
        "taxonomy_rationale": tag.taxonomy_rationale,
        "is_noise": "yes" if tag.is_noise else "no",
    })

    conn = duck()
    row = conn.execute("SELECT text FROM chunks WHERE doc_id = ? AND row_key = ?", [doc_id, row_key]).fetchone()
    if row:
        text = row[0]
        meta_for_issue_key = {"issue_type": updates["issue_type"], "issue_summary": updates["issue_summary"]}
        updates["issue_key"] = _issue_key(text, meta_for_issue_key)

    for key, value in updates.items():
        conn.execute(f"UPDATE chunks SET {key} = ? WHERE doc_id = ? AND row_key = ?", [value, doc_id, row_key])

    table = _lance_table()
    if table is not None:
        table.update(
            where=f"doc_id = {_quote(doc_id)} AND row_key = {_quote(row_key)}",
            values=_filter_lance_values(table, updates),
        )



def delete_chunk(chunk_id: str) -> None:
    if not is_enabled():
        return

    # First get doc_id and row_key to find the corresponding row_id for taxonomy feedback
    row = duck().execute("SELECT doc_id, row_key FROM chunks WHERE chunk_id = ?", [chunk_id]).fetchone()
    if row and row[0] and row[1]:
        doc_id, row_key = row
        row_id = f"{doc_id}::{row_key}"
        duck().execute("DELETE FROM taxonomy_predictions WHERE row_id = ?", [row_id])
        duck().execute("DELETE FROM taxonomy_feedback WHERE row_id = ?", [row_id])

    # Delete from chunks table
    duck().execute("DELETE FROM chunks WHERE chunk_id = ?", [chunk_id])

    table = _lance_table()
    if table is not None:
        table.delete(f"chunk_id = {_quote(chunk_id)}")


def update_chunk_tags(chunk_id: str, tags: list[str]) -> None:
    if not is_enabled():
        return
    tags_str = ",".join(tags)
    duck().execute("UPDATE chunks SET tags = ? WHERE chunk_id = ?", [tags_str, chunk_id])
    table = _lance_table()
    if table is not None:
        table.update(
            where=f"chunk_id = {_quote(chunk_id)}",
            values={"tags": tags_str},
        )


def update_doc_metadata(doc_id: str, category: str | None = None, sprint: str | None = None) -> None:
    if not is_enabled():
        return
    updates = {}
    if category is not None:
        updates["category"] = category
    if sprint is not None:
        updates["sprint"] = sprint
    if not updates:
        return

    conn = duck()
    for key, value in updates.items():
        conn.execute(f"UPDATE chunks SET {key} = ? WHERE doc_id = ?", [value, doc_id])

    table = _lance_table()
    if table is not None:
        table.update(
            where=f"doc_id = {_quote(doc_id)}",
            values=_filter_lance_values(table, updates),
        )

def _where_sql(
    category: str | None = None,
    sprint: str | None = None,
    tag: str | None = None,
    doc_id: str | None = None,
    is_issue: str | None = None,
    issue_type: str | None = None,
    owner: str | None = None,
    status: str | None = None,
    include_noise: bool = False,
) -> tuple[str, list]:
    clauses = []
    params = []
    for column, value in (
        ("category", category),
        ("sprint", sprint),
        ("doc_id", doc_id),
        ("is_issue", issue_fields.normalize_is_issue(is_issue) if is_issue else None),
        ("issue_type", issue_type),
        ("owner", owner),
        ("status", issue_fields.normalize_status(status) if status else None),
    ):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    if tag:
        if tag == UNTAGGED:
            clauses.append("COALESCE(tags, '') = ''")
        else:
            clauses.append("contains(',' || COALESCE(tags, '') || ',', ?)")
            params.append(f",{tag},")
    if not include_noise:
        clauses.append("COALESCE(is_noise, 'no') != 'yes'")
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def list_memories(
    category: str | None = None,
    sprint: str | None = None,
    tag: str | None = None,
    doc_id: str | None = None,
    q: str | None = None,
    limit: int = 5000,
    is_issue: str | None = None,
    issue_type: str | None = None,
    owner: str | None = None,
    status: str | None = None,
    include_noise: bool = False,
) -> list[dict]:
    where, params = _where_sql(category, sprint, tag, doc_id, is_issue, issue_type, owner, status, include_noise)

    # Handle the 'q' parameter for keyword search
    if q and q.strip():
        search_term = f"%{q.strip()}%"
        if where:
            where += " AND text LIKE ?"
        else:
            where = " WHERE text LIKE ?"
        params.append(search_term)
    rows = duck().execute(
        f"""
        SELECT chunk_id, doc_id, title, category, code, sprint, language, video_code, sheet, row_index, row_key,
               tags, is_issue, issue_summary, issue_type, owner, status, issue_source, is_noise,
               taxonomy_category, taxonomy_subcategory, taxonomy_tags, taxonomy_confidence, taxonomy_rationale,
               retake_explicit, retake_terms, issue_key, text, word_count, processed_at
        FROM chunks
        {where}
        ORDER BY code, sheet, row_index, chunk_id
        LIMIT ?
        """,
        [*params, limit],
    ).fetchall()
    return [_memory_from_row(row) for row in rows]


def _memory_from_row(row: tuple) -> dict:
    if len(row) == len(CHUNK_SELECT_COLUMNS) - 1:
        row = (*row, None)
    (
        chunk_id, doc_id, title, category, code, sprint, language, video_code, sheet, row_index, row_key,
        tags, is_issue, issue_summary, issue_type, owner, status, issue_source, is_noise,
        taxonomy_category, taxonomy_subcategory, taxonomy_tags, taxonomy_confidence, taxonomy_rationale,
        retake_explicit, retake_terms, issue_key, text, word_count, processed_at
    ) = row
    return {
        "chunk_id": chunk_id,
        "text": text,
        "metadata": {
            "doc_id": doc_id,
            "title": title,
            "category": category,
            "code": code,
            "sprint": sprint,
            "language": language,
            "video_code": video_code,
            "sheet": sheet,
            "row_index": row_index,
            "row_key": row_key,
            "tags": tags,
            "is_issue": is_issue,
            "issue_summary": issue_summary,
            "issue_type": issue_type,
            "owner": owner,
            "status": status,
            "issue_source": issue_source,
            "is_noise": is_noise,
            "category_tag": taxonomy_category,
            "detail_tags": taxonomy_tags,
            "confidence": taxonomy_confidence,
            "rationale": taxonomy_rationale,
            "taxonomy_category": taxonomy_category,
            "taxonomy_subcategory": taxonomy_subcategory,
            "taxonomy_tags": taxonomy_tags,
            "taxonomy_confidence": taxonomy_confidence,
            "taxonomy_rationale": taxonomy_rationale,
            "retake_explicit": retake_explicit,
            "retake_terms": retake_terms,
            "issue_key": issue_key,
            "word_count": word_count,
            "processed_at": processed_at,
        },
    }


def _top_counts(counter: Counter, limit: int = 100) -> list[dict]:
    return [
        {"key": key, "count": count}
        for key, count in sorted(counter.items(), key=lambda item: (-item[1], str(item[0])))[:limit]
    ]


def _summary_from_memories(memories: list[dict]) -> dict:
    by_tag = Counter()
    by_locale = Counter()
    by_doc = Counter()
    doc_titles = {}
    doc_codes = {}
    for item in memories:
        meta = item["metadata"]
        doc_id = meta.get("doc_id", "")
        doc_titles[doc_id] = meta.get("title", "")
        doc_codes[doc_id] = meta.get("code", "")
        by_doc[doc_id] += 1
        by_locale[meta.get("sheet", "(unknown)") or "(unknown)"] += 1
        for tag in split_tags(meta) or [UNTAGGED]:
            by_tag[tag] += 1

    docs = [
        {
            "doc_id": doc_id,
            "code": doc_codes.get(doc_id, ""),
            "title": doc_titles.get(doc_id, ""),
            "count": count,
        }
        for doc_id, count in sorted(by_doc.items(), key=lambda item: (-item[1], doc_codes.get(item[0], "")))
    ]
    return {
        "total_issues": len(memories),
        "total_docs": len(by_doc),
        "by_doc": docs,
        "by_locale": _top_counts(by_locale),
        "by_tag": _top_counts(by_tag),
    }


def _groups_from_memories(memories: list[dict], limit: int = 1000) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for item in memories:
        meta = item["metadata"]
        key = meta.get("issue_key") or _issue_key(item["text"], meta)
        if not key:
            continue
        grouped.setdefault(key, []).append(item)

    groups = []
    for key, items in grouped.items():
        meta0 = items[0]["metadata"]
        summary = meta0.get("issue_summary") or extract_issue_text(items[0]["text"])[:260]
        locales = sorted({item["metadata"].get("sheet", "(unknown)") or "(unknown)" for item in items})
        docs = {}
        tags = set()
        for item in items:
            meta = item["metadata"]
            docs[meta.get("doc_id", "")] = {
                "doc_id": meta.get("doc_id", ""),
                "code": meta.get("code", ""),
                "title": meta.get("title", ""),
            }
            tags.update(split_tags(meta) or [UNTAGGED])
        groups.append({
            "key": key,
            "summary": summary,
            "count": len(items),
            "locales": locales,
            "docs": sorted(docs.values(), key=lambda doc: doc.get("code", "")),
            "tags": sorted(tags),
            "examples": [memory_example(item) for item in items[:5]],
            "_representative_text": items[0]["text"],
        })
    groups.sort(key=lambda group: (-group["count"], -len(group["locales"]), -len(group["docs"]), group["summary"]))
    return groups[:limit]


def _lance_where(sprint: str, category: str | None, tag: str | None) -> str:
    clauses = [f"sprint = {_quote(sprint)}"]
    if category:
        clauses.append(f"category = {_quote(category)}")
    if tag and tag != UNTAGGED:
        clauses.append(f"tags LIKE {_quote('%' + tag + '%')}")
    if tag == UNTAGGED:
        clauses.append("(tags = '' OR tags IS NULL)")
    return " AND ".join(clauses)


def _semantic_pairs(
    source_groups: list[dict],
    target_groups_by_key: dict[str, dict],
    target_sprint: str,
    category: str | None,
    tag: str | None,
) -> dict[str, str]:
    table = _lance_table()
    if table is None or not source_groups:
        return {}

    vectors = embedder.encode([group["_representative_text"] for group in source_groups])
    matched: dict[str, str] = {}
    used_targets: set[str] = set()
    where = _lance_where(target_sprint, category, tag)
    for group, vector in zip(source_groups, vectors):
        try:
            rows = table.search(vector).metric("cosine").where(where).limit(3).to_list()
        except Exception:
            continue
        for row in rows:
            target_key = row.get("issue_key") or ""
            distance = float(row.get("_distance", 1.0))
            if not target_key or target_key not in target_groups_by_key or target_key in used_targets:
                continue
            if distance <= settings.lance_semantic_match_distance:
                matched[group["key"]] = target_key
                used_targets.add(target_key)
                break
    return matched


def compare_sprints(
    sprint_a: str,
    sprint_b: str,
    tag: str | None = None,
    category: str | None = None,
    limit: int = 5000,
) -> dict:
    memories_a = list_memories(category=category, sprint=sprint_a, tag=tag, limit=limit)
    memories_b = list_memories(category=category, sprint=sprint_b, tag=tag, limit=limit)
    groups_a = _groups_from_memories(memories_a)
    groups_b = _groups_from_memories(memories_b)
    by_key_a = {group["key"]: group for group in groups_a}
    by_key_b = {group["key"]: group for group in groups_b}

    exact_keys = set(by_key_a) & set(by_key_b)
    unresolved_a = [by_key_a[key] for key in set(by_key_a) - exact_keys]
    new_b_keys = set(by_key_b) - exact_keys
    semantic = _semantic_pairs(
        sorted(unresolved_a, key=lambda group: -group["count"])[:80],
        {key: by_key_b[key] for key in new_b_keys},
        sprint_b,
        category,
        tag,
    )

    persistent = []
    for key in sorted(exact_keys):
        persistent.append(_persistent_group(by_key_a[key], by_key_b[key], "exact"))
    for key_a, key_b in semantic.items():
        persistent.append(_persistent_group(by_key_a[key_a], by_key_b[key_b], "semantic"))

    matched_a = set(exact_keys) | set(semantic)
    matched_b = set(exact_keys) | set(semantic.values())
    resolved = sorted(
        (by_key_a[key] for key in set(by_key_a) - matched_a),
        key=lambda group: (-group["count"], group["summary"]),
    )
    new = sorted(
        (by_key_b[key] for key in set(by_key_b) - matched_b),
        key=lambda group: (-group["count"], group["summary"]),
    )
    persistent.sort(key=lambda group: (-(group["count_a"] + group["count_b"]), group["summary"]))

    for group in groups_a + groups_b + resolved + new:
        group.pop("_representative_text", None)
    for group in persistent:
        group.pop("_representative_text", None)

    return {
        "scope": "compare",
        "engine": "duckdb+lance",
        "filters": {
            "sprint_a": sprint_a,
            "sprint_b": sprint_b,
            "tag": tag or "",
            "category": category or "",
        },
        "summary_a": _summary_from_memories(memories_a),
        "summary_b": _summary_from_memories(memories_b),
        "persistent": persistent[:50],
        "resolved": resolved[:50],
        "new": new[:50],
        "diagnostics": {
            "groups_a": len(groups_a),
            "groups_b": len(groups_b),
            "exact_matches": len(exact_keys),
            "semantic_matches": len(semantic),
            "distance_threshold": settings.lance_semantic_match_distance,
        },
    }


def _persistent_group(group_a: dict, group_b: dict, match_type: str) -> dict:
    return {
        "key": group_a["key"],
        "summary": group_a["summary"],
        "count_a": group_a["count"],
        "count_b": group_b["count"],
        "locales_a": group_a["locales"],
        "locales_b": group_b["locales"],
        "docs_a": group_a["docs"],
        "docs_b": group_b["docs"],
        "examples_a": group_a["examples"][:3],
        "examples_b": group_b["examples"][:3],
        "match_type": match_type,
    }


def status() -> dict:
    count_row = duck().execute("SELECT COUNT(*) FROM chunks").fetchone()
    count = count_row[0] if count_row else 0
    tables = _table_names()
    lance_count = _lance_table().count_rows() if TABLE_NAME in tables else 0
    return {
        "enabled": is_enabled(),
        "duckdb_path": str(settings.duckdb_path),
        "lance_dir": str(settings.lance_dir),
        "duckdb_chunks": count,
        "lance_chunks": lance_count,
    }


def stats() -> dict | None:
    if not is_enabled():
        return None
    try:
        conn = duck()
        count_res = conn.execute("SELECT COUNT(*), COUNT(DISTINCT doc_id) FROM chunks").fetchone()
        if not count_res or count_res[0] == 0:
            return None

        def _get_counts(column: str, fallback: str = "") -> dict[str, int]:
            if fallback:
                query = f"SELECT COALESCE(NULLIF({column}, ''), '{fallback}'), COUNT(*) FROM chunks GROUP BY 1"
            else:
                query = f"SELECT {column}, COUNT(*) FROM chunks WHERE {column} IS NOT NULL AND {column} != '' GROUP BY 1"
            return {r[0]: r[1] for r in conn.execute(query).fetchall()}

        def _get_tag_counts() -> dict[str, int]:
            rows = conn.execute("SELECT tags, COUNT(*) FROM chunks WHERE tags IS NOT NULL AND tags != '' GROUP BY 1").fetchall()
            from collections import Counter
            tag_counts = Counter()
            for r in rows:
                for t in r[0].split(','):
                    if t.strip(): tag_counts[t.strip()] += r[1]
            untagged_row = conn.execute("SELECT COUNT(*) FROM chunks WHERE tags IS NULL OR tags = ''").fetchone()
            untagged = untagged_row[0] if untagged_row else 0
            if untagged > 0:
                tag_counts["(untagged)"] = untagged
            return tag_counts

        result = {
            "total_chunks": count_res[0],
            "total_docs": count_res[1],
            "by_category": _get_counts("category", "OTHER"),
            "by_sprint": _get_counts("sprint", "(unassigned)"),
            "by_tag": _get_tag_counts(),
            "by_issue_type": _get_counts("issue_type"),
            "by_owner": _get_counts("owner"),
            "by_status": _get_counts("status"),
            "by_taxonomy_category": _get_counts("taxonomy_category"),
            "by_taxonomy_subcategory": _get_counts("taxonomy_subcategory"),
            "by_retake_explicit": _get_counts("retake_explicit"),
            "embedding_model": settings.embedding_model,
        }
        return result
    except Exception as e:
        print(f"DuckDB stats error: {e}")
        return None


def stats_breakdown(
    category: str | None = None,
    sprint: str | None = None,
    tag: str | None = None,
    doc_id: str | None = None,
) -> dict | None:
    if not is_enabled():
        return None
    try:
        conn = duck()
        where_clause, params = _where_sql(category, sprint, tag, doc_id)

        count_res = conn.execute(f"SELECT COUNT(*), COUNT(DISTINCT doc_id) FROM chunks {where_clause}", params).fetchone()
        if not count_res or count_res[0] == 0:
            return None

        def _get_counts(column: str, fallback: str = "") -> list[dict]:
            if fallback:
                query = f"SELECT COALESCE(NULLIF({column}, ''), '{fallback}'), COUNT(*) FROM chunks {where_clause} GROUP BY 1 ORDER BY 2 DESC, 1"
            else:
                query = f"SELECT {column}, COUNT(*) FROM chunks {where_clause} {'AND' if where_clause else 'WHERE'} {column} IS NOT NULL AND {column} != '' GROUP BY 1 ORDER BY 2 DESC, 1"
            return [{"key": r[0], "count": r[1]} for r in conn.execute(query, params).fetchall()[:100]]

        def _get_tag_counts() -> list[dict]:
            rows = conn.execute(f"SELECT tags, COUNT(*) FROM chunks {where_clause} {'AND' if where_clause else 'WHERE'} tags IS NOT NULL AND tags != '' GROUP BY 1", params).fetchall()
            from collections import Counter
            tag_counts = Counter()
            for r in rows:
                for t in r[0].split(','):
                    if t.strip(): tag_counts[t.strip()] += r[1]
            untagged_row = conn.execute(f"SELECT COUNT(*) FROM chunks {where_clause} {'AND' if where_clause else 'WHERE'} (tags IS NULL OR tags = '')", params).fetchone()
            untagged = untagged_row[0] if untagged_row else 0
            if untagged > 0:
                tag_counts["(untagged)"] = untagged
            return [{"key": k, "count": v} for k, v in sorted(tag_counts.items(), key=lambda x: (-x[1], x[0]))[:100]]

        def _get_doc_counts() -> list[dict]:
            query = f"SELECT doc_id, ANY_VALUE(code), ANY_VALUE(title), COUNT(*) FROM chunks {where_clause} GROUP BY doc_id ORDER BY 4 DESC, 2"
            return [{"doc_id": r[0], "code": r[1] or "", "title": r[2] or "", "count": r[3]} for r in conn.execute(query, params).fetchall()]

        result = {
            "total_chunks": count_res[0],
            "total_docs": count_res[1],
            "filters": {
                "category": category or "",
                "sprint": sprint or "",
                "tag": tag or "",
                "doc_id": doc_id or "",
            },
            "by_category": _get_counts("category", "OTHER"),
            "by_sprint": _get_counts("sprint", "(unassigned)"),
            "by_tag": _get_tag_counts(),
            "by_is_issue": _get_counts("is_issue", "(unknown)"),
            "by_issue_type": _get_counts("issue_type"),
            "by_owner": _get_counts("owner"),
            "by_status": _get_counts("status"),
            "by_taxonomy_category": _get_counts("taxonomy_category"),
            "by_taxonomy_subcategory": _get_counts("taxonomy_subcategory"),
            "by_retake_explicit": _get_counts("retake_explicit"),
            "by_locale": _get_counts("sheet", "(unknown)"),
            "by_doc": _get_doc_counts(),
        }
        return result
    except Exception as e:
        print(f"DuckDB stats_breakdown error: {e}")
        return None


def list_sprints() -> list[str]:
    if not is_enabled():
        return []
    try:
        rows = duck().execute("SELECT DISTINCT sprint FROM chunks WHERE sprint IS NOT NULL AND sprint != '' ORDER BY sprint").fetchall()
        return [row[0] for row in rows]
    except Exception:
        return []


def list_docs(category: str | None = None, sprint: str | None = None) -> list[dict] | None:
    if not is_enabled():
        return None
    try:
        where_clause, params = _where_sql(category, sprint, include_noise=True)
        conn = duck()
        available = {row[1] for row in conn.execute("PRAGMA table_info('chunks')").fetchall()}
        processed_at_expr = "MAX(processed_at)" if "processed_at" in available else "''"
        query = f"SELECT doc_id, ANY_VALUE(code), ANY_VALUE(title), ANY_VALUE(category), ANY_VALUE(sprint), COUNT(*), {processed_at_expr} FROM chunks {where_clause} GROUP BY doc_id ORDER BY ANY_VALUE(code)"
        rows = conn.execute(query, params).fetchall()
        return [
            {
                "doc_id": r[0] if len(r) > 0 else "",
                "code": (r[1] or "") if len(r) > 1 else "",
                "title": (r[2] or "") if len(r) > 2 else "",
                "category": (r[3] or "") if len(r) > 3 else "",
                "sprint": (r[4] or "") if len(r) > 4 else "",
                "chunk_count": r[5] if len(r) > 5 else 0,
                "last_processed_at": (r[6] or "") if len(r) > 6 else "",
            }
            for r in rows
        ]
    except Exception as e:
        print(f"DuckDB list_docs error: {e}")
        return None

def get_chunk(chunk_id: str) -> dict | None:
    if not is_enabled():
        return None
    try:
        conn = duck()
        row = conn.execute("SELECT * FROM chunks WHERE chunk_id = ?", [chunk_id]).fetchone()
        if not row:
            return None
        # We need to map row back to a memory dict. Wait, _memory_from_row maps a specific SELECT order.
        # Let's just fetch exactly what _memory_from_row expects.
        row = conn.execute(
            f"SELECT {_chunk_select_list(conn)} FROM chunks WHERE chunk_id = ?",
            [chunk_id]
        ).fetchone()
        if not row:
            return None
        return _memory_from_row(row)
    except Exception as e:
        print(f"DuckDB get_chunk error: {e}")
        return None

def get_chunks(doc_id: str) -> list[dict] | None:
    if not is_enabled():
        return None
    try:
        conn = duck()
        rows = conn.execute(
            f"SELECT {_chunk_select_list(conn)} FROM chunks WHERE doc_id = ? ORDER BY COALESCE(row_index, 0)",
            [doc_id]
        ).fetchall()
        return [_memory_from_row(r) for r in rows]
    except Exception as e:
        print(f"DuckDB get_chunks error: {e}")
        return None


def _filter_to_lance_where(where: dict | None) -> str | None:
    if not where:
        return None

    def parse_clause(k, v):
        if k == "$and":
            return " AND ".join(_filter_to_lance_where(c) for c in v if _filter_to_lance_where(c))
        if isinstance(v, dict):
            if "$in" in v:
                return f"{k} IN {_in_clause(v['$in'])}"
            if "$eq" in v:
                return f"{k} = {_quote(v['$eq'])}"
        return f"{k} = {_quote(v)}"

    if "$and" in where:
        return f"({parse_clause('$and', where['$and'])})"

    k, v = list(where.items())[0]
    return parse_clause(k, v)


def search(
    query_embedding: list[float],
    top_k: int,
    where: dict | None = None,
    include_embeddings: bool = False,
    ids: list[str] | None = None,
) -> dict | None:
    if not is_enabled():
        return None

    table = _lance_table()
    if table is None:
        return None

    try:
        lance_where = _filter_to_lance_where(where)
        if ids:
            ids_clause = f"chunk_id IN {_in_clause(ids)}"
            lance_where = f"({lance_where}) AND {ids_clause}" if lance_where else ids_clause

        q = table.search(query_embedding).metric("cosine")
        if lance_where:
            q = q.where(lance_where)
        q = q.limit(top_k)

        rows = q.to_list()

        res_ids = []
        res_docs = []
        res_metas = []
        res_distances = []
        res_embeddings = []

        for row in rows:
            res_ids.append(row["chunk_id"])
            res_docs.append(row["text"])
            res_distances.append(float(row.get("_distance", 0.0)))
            if include_embeddings and "vector" in row:
                res_embeddings.append(list(row["vector"]))

            meta = {
                "doc_id": row.get("doc_id", ""),
                "title": row.get("title", ""),
                "category": row.get("category", ""),
                "code": row.get("code", ""),
                "sprint": row.get("sprint", ""),
                "sheet": row.get("sheet", ""),
                "row_index": row.get("row_index", 0),
                "row_key": row.get("row_key", ""),
                "tags": row.get("tags", ""),
                "is_issue": row.get("is_issue", ""),
                "issue_summary": row.get("issue_summary", ""),
                "issue_type": row.get("issue_type", ""),
                "owner": row.get("owner", ""),
                "status": row.get("status", ""),
                "issue_source": row.get("issue_source", ""),
                "taxonomy_category": row.get("taxonomy_category", ""),
                "taxonomy_subcategory": row.get("taxonomy_subcategory", ""),
                "taxonomy_tags": row.get("taxonomy_tags", ""),
                "taxonomy_confidence": row.get("taxonomy_confidence", 0.0),
                "taxonomy_rationale": row.get("taxonomy_rationale", ""),
                "retake_explicit": row.get("retake_explicit", ""),
                "retake_terms": row.get("retake_terms", ""),
                "processed_at": row.get("processed_at", ""),
            }
            res_metas.append({k: v for k, v in meta.items() if v is not None and str(v) != ""})

        result = {
            "ids": [res_ids],
            "documents": [res_docs],
            "metadatas": [res_metas],
            "distances": [res_distances],
        }
        if include_embeddings:
            result["embeddings"] = [res_embeddings]
        return result
    except Exception as e:
        print(f"LanceDB search error: {e}")
        return None


def get_chunk_ids(where: dict | None = None, tags: list[str] | None = None) -> list[str]:
    if not is_enabled():
        return []

    conn = duck()
    clauses = []

    if where:
        lance_where = _filter_to_lance_where(where)
        if lance_where:
            clauses.append(lance_where)

    if tags:
        tag_clauses = []
        for tag in tags:
            if tag == '(untagged)':
                tag_clauses.append("(tags = '' OR tags IS NULL)")
            else:
                tag_clauses.append(f"tags LIKE {_quote('%' + tag + '%')}")
        if tag_clauses:
            clauses.append("(" + " OR ".join(tag_clauses) + ")")

    query = "SELECT chunk_id FROM chunks"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)

    rows = conn.execute(query).fetchall()
    return [r[0] for r in rows]


def backfill_retake_fields(limit: int | None = None) -> dict:
    if not is_enabled():
        return {"updated": 0, "scanned": 0}

    from . import retake_detector

    conn = duck()
    query = "SELECT chunk_id, text, retake_explicit, retake_terms FROM chunks ORDER BY chunk_id"
    params: list[object] = []
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(query, params).fetchall()

    table = _lance_table()
    scanned = 0
    updated = 0
    for chunk_id, text, current_explicit, current_terms in rows:
        scanned += 1
        detected = retake_detector.detect_explicit_retake(text or "")
        next_explicit = detected["retake_explicit"]
        next_terms = detected["retake_terms"]
        if (current_explicit or "") == next_explicit and (current_terms or "") == next_terms:
            continue

        conn.execute(
            "UPDATE chunks SET retake_explicit = ?, retake_terms = ? WHERE chunk_id = ?",
            [next_explicit, next_terms, chunk_id],
        )
        if table is not None:
            table.update(
                where=f"chunk_id = {_quote(chunk_id)}",
                values=_filter_lance_values(table, {
                    "retake_explicit": next_explicit,
                    "retake_terms": next_terms,
                }),
            )
        updated += 1

    return {"updated": updated, "scanned": scanned}
