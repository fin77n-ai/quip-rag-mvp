"""Persist per-doc row-level tags. data/row_tags/{doc_id}.json"""
from pathlib import Path
from ..config import settings
from ..models.tags import DocTags, RowTag


_DIR = settings.row_tags_dir
_DIR.mkdir(parents=True, exist_ok=True)


def path_for(doc_id: str) -> Path:
    return _DIR / f"{doc_id}.json"


def load(doc_id: str) -> DocTags:
    p = path_for(doc_id)
    if not p.exists():
        return DocTags(doc_id=doc_id)
    return DocTags.model_validate_json(p.read_text(encoding="utf-8"))


def save(tags: DocTags) -> Path:
    for row_tag in tags.rows.values():
        _normalize_row_tag(row_tag)
    p = path_for(tags.doc_id)
    p.write_text(tags.model_dump_json(indent=2), encoding="utf-8")
    return p


def set_row(doc_id: str, key: str, tag: RowTag) -> DocTags:
    _normalize_row_tag(tag)
    dt = load(doc_id)
    if not _is_meaningful(tag):
        dt.rows.pop(key, None)
    else:
        dt.rows[key] = tag
    save(dt)
    return dt


def delete_row(doc_id: str, key: str) -> DocTags:
    dt = load(doc_id)
    dt.rows.pop(key, None)
    save(dt)
    return dt


def delete_rows(doc_id: str, keys: list[str]) -> DocTags:
    dt = load(doc_id)
    for key in keys:
        dt.rows.pop(key, None)
    save(dt)
    return dt


def all_known_tags() -> list[str]:
    """Union of every tag string across all docs (for autocomplete)."""
    seen: set[str] = set()
    for f in _DIR.glob("*.json"):
        try:
            dt = DocTags.model_validate_json(f.read_text(encoding="utf-8"))
            for r in dt.rows.values():
                seen.update(r.tags)
        except Exception:
            continue
    return sorted(seen)


def all_known_detail_tags() -> list[str]:
    seen: set[str] = set()
    for f in _DIR.glob("*.json"):
        try:
            dt = DocTags.model_validate_json(f.read_text(encoding="utf-8"))
            for row in dt.rows.values():
                seen.update(row.detail_tags or row.taxonomy_tags)
        except Exception:
            continue
    return sorted(tag for tag in seen if tag)


def clear_excluded(doc_id: str) -> DocTags:
    dt = load(doc_id)
    for key, row in list(dt.rows.items()):
        row.excluded = False
        row.is_noise = False
        _normalize_row_tag(row)
        if not _is_meaningful(row):
            dt.rows.pop(key, None)
    save(dt)
    return dt


def iter_all() -> list[DocTags]:
    docs: list[DocTags] = []
    for f in sorted(_DIR.glob("*.json")):
        try:
            docs.append(DocTags.model_validate_json(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return docs


def _normalize_row_tag(tag: RowTag) -> None:
    if tag.category_tag and not tag.taxonomy_category:
        tag.taxonomy_category = tag.category_tag
    if tag.taxonomy_category and not tag.category_tag:
        tag.category_tag = tag.taxonomy_category

    if tag.detail_tags and not tag.taxonomy_tags:
        tag.taxonomy_tags = list(dict.fromkeys(tag.detail_tags))[:5]
    if tag.taxonomy_tags and not tag.detail_tags:
        tag.detail_tags = list(dict.fromkeys(tag.taxonomy_tags))[:5]
    if tag.detail_tags:
        tag.detail_tags = list(dict.fromkeys([item.strip() for item in tag.detail_tags if item.strip()]))[:5]
    if tag.taxonomy_tags:
        tag.taxonomy_tags = list(dict.fromkeys([item.strip() for item in tag.taxonomy_tags if item.strip()]))[:5]

    if tag.confidence and not tag.taxonomy_confidence:
        tag.taxonomy_confidence = tag.confidence
    if tag.taxonomy_confidence and not tag.confidence:
        tag.confidence = tag.taxonomy_confidence

    if tag.rationale and not tag.taxonomy_rationale:
        tag.taxonomy_rationale = tag.rationale
    if tag.taxonomy_rationale and not tag.rationale:
        tag.rationale = tag.taxonomy_rationale


def _is_meaningful(tag: RowTag) -> bool:
    return any([
        tag.tags,
        tag.excluded,
        tag.is_noise,
        tag.category_tag,
        tag.detail_tags,
        tag.review_required,
        tag.is_issue,
        tag.issue_summary,
        tag.issue_type,
        tag.owner,
        tag.status,
    ])
