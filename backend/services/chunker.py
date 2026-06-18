import datetime
from ..models.quip import ParsedDoc
from . import issue_fields, rules_store, tags_store


def chunk_doc(doc: ParsedDoc) -> list[dict]:
    """
    Chunking strategy:
      • Table rows → each row = 1 chunk (using already-filtered cells from parser)
      • Plain-text sections (no [TABLE] markers) → kept as section chunks
    """
    rules = rules_store.load()
    chunks: list[dict] = []

    # Row-as-chunk for tables (always when table_rows present)
    if doc.table_rows:
        doc_tags = tags_store.load(doc.doc_id)
        for row in doc.table_rows:
            sheet = row.get("sheet", "")
            row_idx = row.get("row_index", 0)
            cells = row.get("cells", {})
            row_key = f"{sheet}::{row_idx}"
            row_tag = doc_tags.rows.get(row_key)
            if row_tag and row_tag.excluded:
                continue
            text_parts = [f"{h}: {v.strip()}" for h, v in cells.items()
                          if v and v.strip() and v.strip() not in ("​", "—", "-")]
            if not text_parts:
                continue

            # Enrich text with document context so LLMs have full context
            context_header = f"[TITLE] {doc.title}\n[SHEET] {sheet}\n---\n"
            text = context_header + "\n".join(text_parts)

            if len(text) < rules.min_chunk_chars:
                continue
            tags_for_row = row_tag.tags if row_tag else []
            parsed_issue_fields = dict(row.get("issue_fields") or {})
            parsed_issue_fields.update(issue_fields.extract_issue_fields(cells))
            chunks.append(_make_row_chunk(doc, text, sheet, row_idx, tags_for_row, row_tag, parsed_issue_fields, len(chunks)))

    # Plain-text sections (skip table blocks — they're handled above as row chunks)
    for section in doc.sections:
        if not section.strip() or "[TABLE" in section:
            continue
        if len(section) < rules.min_chunk_chars:
            continue
        # Enrich section text as well
        context_header = f"[TITLE] {doc.title}\n---\n"
        enriched_section = context_header + section
        chunks.append(_make_chunk(doc, enriched_section, len(chunks)))

    return chunks


def _make_chunk(doc: ParsedDoc, text: str, index: int) -> dict:
    """Generic chunk (non-row). Doc-level tag union."""
    embed_text = f"[CODE] {doc.code}\n{text}"
    doc_tags_obj = tags_store.load(doc.doc_id)
    tag_set = set()
    for r in doc_tags_obj.rows.values():
        tag_set.update(r.tags)
    return _chunk_dict(doc, text, embed_text, index, sorted(tag_set))


def _make_row_chunk(doc: ParsedDoc, text: str, sheet: str, row_idx: int,
                    tags: list[str], row_tag, parsed_issue_fields: dict[str, str], index: int) -> dict:
    """Per-row chunk with precise row-level tags."""
    merged_issue_fields = issue_fields.merge_issue_fields(parsed_issue_fields, row_tag)
    short_text = _issue_context_lines(text, merged_issue_fields)
    embed_text = f"[CODE] {doc.code}\n{short_text}"
    base = _chunk_dict(doc, short_text, embed_text, index, tags)
    merged_issue_fields = issue_fields.merge_issue_fields(parsed_issue_fields, row_tag)

    from .metadata_normalizer import normalize_metadata
    sprint_meta, language, video_code = normalize_metadata(doc.title, sheet)

    base["metadata"].update({
        "sheet": sheet,
        "language": language,
        "video_code": video_code,
        "sprint": sprint_meta or doc.sprint or "",
        "row_index": row_idx,
        "row_key": f"{sheet}::{row_idx}",
        "category_tag": row_tag.category_tag if row_tag else "",
        "detail_tags": ",".join(row_tag.detail_tags if row_tag else []),
        "confidence": float(row_tag.confidence if row_tag else 0.0),
        "review_required": "yes" if row_tag and row_tag.review_required else "no",
        "review_reason": row_tag.review_reason if row_tag else "",
        "issue_source": row_tag.issue_source if row_tag else "",
        "taxonomy_category": row_tag.taxonomy_category if row_tag else "",
        "taxonomy_tags": ",".join(row_tag.taxonomy_tags if row_tag else []),
        "taxonomy_confidence": float(row_tag.taxonomy_confidence if row_tag else 0.0),
        "taxonomy_rationale": row_tag.taxonomy_rationale if row_tag else "",
    })
    base["metadata"].update(merged_issue_fields)
    return base


def _chunk_dict(doc: ParsedDoc, text: str, embed_text: str, index: int, tags: list[str]) -> dict:
    return {
        "id": f"{doc.doc_id}::{index}",
        "text": text,
        "embed_text": embed_text,
        "metadata": {
            "doc_id": doc.doc_id,
            "chunk_index": index,
            "title": doc.title,
            "category": doc.prefix,
            "code": doc.code,
            "sprint": doc.sprint or "",
            "tags": ",".join(tags),
            "word_count": len(text.split()),
            "processed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
    }


def _issue_context_lines(text: str, issue_meta: dict[str, str]) -> str:
    lines = []
    summary = issue_meta.get("issue_summary")
    if summary:
        lines.append(f"Issue: {summary}")
    if issue_meta.get("issue_type"):
        lines.append(f"Issue Type: {issue_meta['issue_type']}")

    for line in text.splitlines():
        if line.startswith("Issue One-liner:") or line.startswith("Issue?:") or line.startswith("Issue Type:"):
            continue
        lines.append(line)
    return "\n".join(lines)
