import re
import json
from datetime import datetime, timezone
from pathlib import Path
from bs4 import BeautifulSoup

from ..models.quip import RawQuipDoc, ParsedDoc
from ..models.rules import FilterRules
from ..models.tags import DocTags
from . import rules_store, tags_store


_CODE_RE = re.compile(r'^([A-Z]+)(\d+)[_\-]')


def _extract_prefix_and_code(title: str) -> tuple[str, str]:
    m = _CODE_RE.match(title)
    if not m:
        return "OTHER", "OTHER"
    return m.group(1), m.group(1) + m.group(2)


def _is_placeholder(text: str, placeholders: set[str]) -> bool:
    t = (text or "").strip()
    return not t or t in placeholders


def _detect_header_row(rows, max_check: int = 5) -> int:
    """Spreadsheet exports often have row-letter / section-label rows before the real header.
    Pick the row in the first N with the most distinct non-trivial cells."""
    placeholder_set = {"", "​", "—", "-", "n/a", "N/A"}
    best_idx = 0
    best_score = -1
    for i, row in enumerate(rows[:max_check]):
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
        # ignore single-letter cells (A, B, C...) — those are column-letter rows
        scoreable = [c for c in cells if c and c not in placeholder_set
                     and not (len(c) == 1 and c.isalpha())]
        score = len(scoreable)
        if score > best_score:
            best_score = score
            best_idx = i
    return best_idx


def _table_to_text(table, rules: FilterRules, sheet_name: str, doc_tags: DocTags | None) -> tuple[str, dict, list[dict]]:
    """Convert an HTML table to readable text + structured rows.
    Returns (text, stats, structured_rows)."""
    rows = table.find_all("tr")
    placeholders = set(rules.placeholder_chars)
    norm = lambda s: re.sub(r"\s+", " ", (s or "").strip()).lower()
    exclude_cols_lower = {norm(c) for c in rules.exclude_columns}
    include_cols_lower = {norm(c) for c in rules.include_columns}
    row_patterns = [re.compile(p, re.IGNORECASE) for p in rules.exclude_row_patterns]

    header_idx = _detect_header_row(rows)
    headers: list[str] = []
    keep_col_idx: list[int] = []
    out_lines: list[str] = []
    structured: list[dict] = []
    rows_total = 0
    rows_kept = 0
    cols_dropped = 0
    user_excluded = 0

    for i, row in enumerate(rows):
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
        if not cells:
            continue
        rows_total += 1

        if i < header_idx:
            continue   # pre-header noise (column letters, section bars)

        if i == header_idx:
            # Disambiguate duplicate column names
            seen: dict[str, int] = {}
            disambiguated = []
            for h in cells:
                n = seen.get(h, 0) + 1
                seen[h] = n
                disambiguated.append(h if n == 1 else f"{h} ({n})")
            headers = disambiguated
            # include_columns is a WHITELIST. If set, only keep those columns.
            # Else, drop anything in exclude_columns.
            if include_cols_lower:
                keep_col_idx = [j for j, h in enumerate(headers) if norm(h) in include_cols_lower]
            else:
                keep_col_idx = [j for j, h in enumerate(headers) if norm(h) not in exclude_cols_lower]
            cols_dropped = len(headers) - len(keep_col_idx)
            kept_headers = [headers[j] for j in keep_col_idx]
            out_lines.append(" | ".join(kept_headers))
            rows_kept += 1
            continue

        # User per-row exclusion (tags layer)
        # Note: excluded rows are completely skipped (not included in output or preview)
        row_key = f"{sheet_name}::{i}"
        if doc_tags and row_key in doc_tags.rows and doc_tags.rows[row_key].excluded:
            user_excluded += 1
            continue

        kept_cells = [cells[j] if j < len(cells) else "" for j in keep_col_idx]

        # Drop row if all KEPT cells are placeholders/empty (more meaningful than the
        # old "all cells empty" check since we now know what columns matter)
        if all(_is_placeholder(c, placeholders) for c in kept_cells):
            continue

        full_row_text = " ".join(kept_cells)
        if any(p.search(full_row_text) for p in row_patterns):
            continue

        rows_kept += 1
        out_lines.append(" | ".join(c if c else "​" for c in kept_cells))
        if headers and len(headers) == len(cells):
            # structured cells contains ONLY kept columns so chunker sees clean data
            cell_dict = {headers[j]: cells[j] for j in keep_col_idx if j < len(cells)}
            structured.append({"sheet": sheet_name, "row_index": i, "cells": cell_dict})

    stats = {
        "rows_total": rows_total,
        "rows_kept": rows_kept,
        "rows_dropped": rows_total - rows_kept,
        "cols_dropped": cols_dropped,
        "user_excluded": user_excluded,
    }
    return "\n".join(out_lines), stats, structured


def _html_to_sections(html: str, rules: FilterRules, doc_tags: DocTags | None = None) -> tuple[str, list[str], dict, list[dict]]:
    """Parse HTML applying FilterRules + per-row tag-based excludes.
    Returns (plain_text, sections, parse_stats, all_table_rows)."""
    soup = BeautifulSoup(html, "lxml")
    excluded_sheets = {t.strip().lower() for t in rules.exclude_sheets}
    heading_patterns = [re.compile(p, re.IGNORECASE) for p in rules.exclude_section_headings]

    sheet_breakdown: list[dict] = []
    all_rows: list[dict] = []
    table_blocks: list[str] = []

    for table in soup.find_all("table"):
        sheet_title = (table.get("title") or "").strip()
        if sheet_title.lower() in excluded_sheets:
            sheet_breakdown.append({"sheet": sheet_title or "(untitled)", "kept": False, "reason": "excluded sheet"})
            table.replace_with(soup.new_string(""))
            continue
        readable, stats, structured = _table_to_text(table, rules, sheet_title or "(untitled)", doc_tags)
        sheet_breakdown.append({"sheet": sheet_title or "(untitled)", "kept": True, **stats})
        all_rows.extend(structured)
        label = f"[TABLE: {sheet_title}]" if sheet_title else "[TABLE]"
        table_blocks.append(f"{label}\n{readable}\n[/TABLE]")
        table.replace_with(soup.new_string(f"\n{label}\n{readable}\n[/TABLE]\n"))

    # Split by headings (h1-h4), applying heading regex filter
    sections: list[str] = []
    current_heading = ""
    current_lines: list[str] = []
    skip_current = False

    def flush():
        nonlocal current_lines, skip_current
        if current_lines and not skip_current:
            sections.append(f"{current_heading}\n{' '.join(current_lines)}".strip())
        current_lines = []
        skip_current = False

    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "div"]):
        if el.name in ("h1", "h2", "h3", "h4"):
            flush()
            current_heading = el.get_text(" ", strip=True)
            skip_current = any(p.search(current_heading) for p in heading_patterns)
        else:
            text = el.get_text(" ", strip=True)
            if text:
                current_lines.append(text)
    flush()

    # Min chunk length filter
    if rules.min_chunk_chars > 0:
        sections = [s for s in sections if len(s) >= rules.min_chunk_chars]

    full_text = "\n\n".join(sections)
    if table_blocks:
        full_text = "\n\n".join([block for block in [full_text, *table_blocks] if block.strip()])
    parse_stats = {"sheet_breakdown": sheet_breakdown, "sections_kept": len(sections)}
    return full_text, sections, parse_stats, all_rows


def _parse_plain_table_rows(text: str, rules: FilterRules) -> tuple[str, list[str], dict, list[dict]]:
    sheet_breakdown = []
    sections: list[str] = []
    rows: list[dict] = []
    full_text = str(text or "")
    table_match = re.search(r"\[TABLE(?:\:\s*([^\]]+))?\](.*?)\[/TABLE\]", full_text, re.S)
    if not table_match:
        return full_text, [full_text] if full_text.strip() else [], {"sheet_breakdown": []}, []

    sheet = (table_match.group(1) or "(untitled)").strip()
    body = [line.strip() for line in table_match.group(2).splitlines() if line.strip()]
    if not body:
        return full_text, sections, {"sheet_breakdown": [{"sheet": sheet, "kept": True, "rows_total": 0, "rows_kept": 0, "rows_dropped": 0, "cols_dropped": 0}]}, []

    rows_total = 0
    rows_kept = 0
    headers: list[str] = []
    header_keys: list[str] = []
    for line in body:
        rows_total += 1
        if line.startswith("|"):
            continue
        if line.startswith(":"):
            parts = [part.strip() for part in line[1:].split(",")]
            row_index = None
            values: dict[str, str] = {}
            for part in parts:
                if part.isdigit():
                    row_index = int(part)
                    continue
                if ": " not in part:
                    continue
                key, value = part.split(": ", 1)
                key = key.strip()
                value = value.strip()
                if key.isdigit():
                    row_index = int(key)
                    continue
                values[key] = value
            if not headers and row_index == 1:
                header_keys = list(values.keys())
                headers = list(values.values())
                continue
            if headers and row_index is not None:
                kept = {}
                for idx, header in enumerate(headers):
                    if rules.include_columns and header not in rules.include_columns:
                        continue
                    source_key = header_keys[idx] if idx < len(header_keys) else header
                    kept[header] = values.get(source_key, values.get(header, ""))
                rows.append({"sheet": sheet, "row_index": row_index, "cells": kept})
                rows_kept += 1
        else:
            headers = [part.strip() for part in line.split("|") if part.strip()]

    sheet_breakdown.append({
        "sheet": sheet,
        "kept": True,
        "rows_total": rows_total,
        "rows_kept": rows_kept,
        "rows_dropped": max(rows_total - rows_kept, 0),
        "cols_dropped": 0,
    })
    return full_text, [full_text], {"sheet_breakdown": sheet_breakdown, "sections_kept": 1}, rows


def parse_dict(data: dict, rules: FilterRules | None = None) -> ParsedDoc:
    """Parse a Quip dict applying global FilterRules at parse time."""
    thread = data.get("thread") or {}
    thread_id = data.get("thread_id") or data.get("id") or data.get("doc_id") or thread.get("id")
    if not thread_id:
        raise ValueError(f"JSON missing thread_id/id/doc_id. Available keys: {list(data.keys())}")

    if rules is None:
        rules = rules_store.load()

    # html fallback: if slim JSON only has plain text under another name, wrap it as minimal HTML
    html = data.get("html") or ""
    plain_text_fallback = None
    if not html:
        for alt in ("body", "text", "plain_text", "content", "markdown"):
            txt = data.get(alt)
            if txt:
                plain_text_fallback = str(txt)
                paragraphs = [p.strip() for p in str(txt).split("\n\n") if p.strip()]
                html = "\n".join(f"<p>{p}</p>" for p in paragraphs) or f"<p>{txt}</p>"
                break
        if not html:
            raise ValueError(f"JSON has no html/body/text/plain_text/content. Keys: {list(data.keys())}")

    now_us = int(datetime.now(tz=timezone.utc).timestamp() * 1_000_000)
    raw = RawQuipDoc(
        source=data.get("source", "quip"),
        thread_id=thread_id,
        title=data.get("title") or thread.get("title") or thread_id,
        created_usec=int(data.get("created_usec") or thread.get("created_usec") or now_us),
        updated_usec=int(data.get("updated_usec") or thread.get("updated_usec") or now_us),
        html=html,
        comments=data.get("comments", []) or [],
        raw=data,
    )
    parsed = _parse_raw(raw, rules)
    if plain_text_fallback and "[TABLE" in plain_text_fallback and not parsed.table_rows:
        plain_text, sections, _stats, table_rows = _parse_plain_table_rows(plain_text_fallback, rules)
        parsed = parsed.model_copy(update={
            "plain_text": plain_text,
            "sections": sections,
            "word_count": len(plain_text.split()),
            "table_rows": table_rows,
        })
    return parsed


def preview_dict(data: dict, rules: FilterRules) -> dict:
    """Like parse_dict but skips the cache and returns rich preview stats."""
    thread = data.get("thread") or {}
    thread_id = data.get("thread_id") or data.get("id") or data.get("doc_id") or thread.get("id") or "(no id)"
    title = data.get("title") or thread.get("title") or thread_id
    html = data.get("html") or ""
    plain_text_fallback = None
    if not html:
        for alt in ("body", "text", "plain_text", "content", "markdown"):
            if data.get(alt):
                plain_text_fallback = str(data[alt])
                html = f"<p>{data[alt]}</p>"
                break
    full_text, sections, stats, table_rows = _html_to_sections(html, rules, None)
    if plain_text_fallback and "[TABLE" in plain_text_fallback and not table_rows:
        full_text, sections, stats, table_rows = _parse_plain_table_rows(plain_text_fallback, rules)
    if rules.min_chunk_chars > 0:
        sections = [s for s in sections if len(s) >= rules.min_chunk_chars]
    return {
        "doc_id": thread_id,
        "title": title,
        "stats": stats,
        "sections_count": len(sections),
        "table_rows_count": len(table_rows),
        "total_chars": len(full_text),
        "sample_text": full_text,   # local app — send everything, no truncation
    }


def _parse_raw(raw: RawQuipDoc, rules: FilterRules | None = None) -> ParsedDoc:
    if rules is None:
        rules = rules_store.load()
    doc_tags = tags_store.load(raw.thread_id)
    plain_text, sections, _stats, table_rows = _html_to_sections(raw.html, rules, doc_tags)
    prefix, code = _extract_prefix_and_code(raw.title)
    return ParsedDoc(
        doc_id=raw.thread_id,
        title=raw.title,
        prefix=prefix,
        code=code,
        table_rows=table_rows,
        plain_text=plain_text,
        sections=sections,
        word_count=len(plain_text.split()),
        created_at=datetime.fromtimestamp(raw.created_usec / 1_000_000, tz=timezone.utc),
        updated_at=datetime.fromtimestamp(raw.updated_usec / 1_000_000, tz=timezone.utc),
        comment_count=len(raw.comments),
    )
