from pathlib import Path
import json
import re
from collections import Counter, defaultdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..models.tags import DocTags, RowTag
from ..models.taxonomy import TaxonomyFeedbackRequest
from ..services import tags_store, taxonomy_store, vector_store, auto_tagger

router = APIRouter(prefix="/tags", tags=["tags"])
_BROAD_CATEGORY_TAGS = ["Animation", "Translation", "Voice Over", "Source"]
_TAG_TAXONOMY = {
    "Animation": ["validation", "post editing", "ui capture", "motion timing", "layout"],
    "Translation": ["validation", "terminology", "locale difference", "ui text", "instructions"],
    "Voice Over": ["validation", "script mismatch", "audio quality", "pronunciation", "pacing", "retake"],
    "Source": ["validation", "source mismatch", "guidance", "locale difference", "source asset"],
}

_FEEDBACK_PATH = Path("data/feedback/tag_feedback.jsonl")
_DISTILLED_PATH = Path("data/feedback/tag_feedback_distilled.json")
_FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)


class ReviewQueueResponse(BaseModel):
    rows: list[dict] = Field(default_factory=list)


class DistillResponse(BaseModel):
    rules: list[str] = Field(default_factory=list)
    examples: list[dict] = Field(default_factory=list)
    total_feedback: int = 0


class TagCandidate(BaseModel):
    tag: str
    count: int
    categories: dict[str, int] = Field(default_factory=dict)


class TagTaxonomyResponse(BaseModel):
    categories: dict[str, list[str]]
    candidates: list[TagCandidate] = Field(default_factory=list)


class DetailTagMergeRequest(BaseModel):
    from_tag: str
    to_tag: str
    category: str = ""


class DetailTagMergeResponse(BaseModel):
    updated_rows: int
    synced_chunks: int


@router.get("")
async def list_known_tags():
    active_tags, active_loose_tags = _active_detail_tag_stats()
    controlled_detail_tags = list(dict.fromkeys(tag for tags in _TAG_TAXONOMY.values() for tag in tags))
    return {
        "tags": _BROAD_CATEGORY_TAGS,
        "detail_tags": controlled_detail_tags,
        "active_detail_tags_count": active_tags,
        "loose_detail_tags_count": active_loose_tags,
    }


@router.get("/taxonomy", response_model=TagTaxonomyResponse)
async def tag_taxonomy():
    return TagTaxonomyResponse(categories=_TAG_TAXONOMY, candidates=_detail_tag_candidates())


@router.post("/detail-tags/merge", response_model=DetailTagMergeResponse)
async def merge_detail_tag(req: DetailTagMergeRequest):
    from_tag = _clean_single_tag(req.from_tag)
    to_tag = _clean_single_tag(req.to_tag)
    category = _clean_single_tag(req.category)
    if not from_tag or not to_tag:
        raise HTTPException(status_code=400, detail="from_tag and to_tag are required")
    if category and category not in _TAG_TAXONOMY:
        raise HTTPException(status_code=400, detail=f"Unknown category: {category}")

    updated_rows = 0
    synced_chunks = 0
    for doc_tags in tags_store.iter_all():
        changed_keys: list[str] = []
        next_rows = {}
        for key, row in doc_tags.rows.items():
            updated = _merge_row_detail_tag(row, from_tag, to_tag, category)
            next_rows[key] = updated
            if updated.model_dump() != row.model_dump():
                changed_keys.append(key)

        if not changed_keys:
            continue

        saved_doc = doc_tags.model_copy(update={"rows": next_rows})
        tags_store.save(saved_doc)
        updated_rows += len(changed_keys)
        for key in changed_keys:
            synced_chunks += vector_store.sync_row_tag(saved_doc.doc_id, key, saved_doc.rows[key])

    return DetailTagMergeResponse(updated_rows=updated_rows, synced_chunks=synced_chunks)


@router.get("/review-queue", response_model=ReviewQueueResponse)
async def review_queue():
    return ReviewQueueResponse(rows=vector_store.list_review_rows())


@router.get("/noise", response_model=ReviewQueueResponse)
async def noise_rows():
    return ReviewQueueResponse(rows=vector_store.list_noise_rows())


@router.post("/feedback/distill", response_model=DistillResponse)
async def distill_feedback():
    items = _read_feedback()
    distilled = _distill(items)
    _DISTILLED_PATH.write_text(json.dumps(distilled, ensure_ascii=False, indent=2), encoding="utf-8")
    return DistillResponse(**distilled)


@router.get("/{doc_id}", response_model=DocTags)
async def get_tags(doc_id: str):
    return tags_store.load(doc_id)


def _mark_row_excluded(doc_id: str, key: str) -> bool:
    tags_doc = tags_store.load(doc_id)
    if key not in tags_doc.rows:
        return False
    updated_tag = tags_doc.rows[key].model_copy(update={"excluded": True})
    tags_store.set_row(doc_id, key, updated_tag)
    return True


def _mark_row_noise(doc_id: str, key: str) -> bool:
    tags_doc = tags_store.load(doc_id)
    existing = tags_doc.rows.get(key, RowTag())
    updated_tag = existing.model_copy(update={
        "excluded": True,
        "is_noise": True,
        "review_required": False,
        "review_reason": "Marked as noise; hidden from search but kept for reference.",
    })
    tags_store.set_row(doc_id, key, updated_tag)
    vector_store.sync_row_tag(doc_id, key, updated_tag)
    return True


@router.post("/{doc_id}/row/{key:path}/noise")
async def archive_row_as_noise(doc_id: str, key: str):
    _mark_row_noise(doc_id, key)
    return {"archived": 1}


@router.delete("/{doc_id}/row/{key:path}")
async def delete_row_chunk(doc_id: str, key: str):
    deleted_count = vector_store.delete_chunk_by_row(doc_id, key)
    tags_store.delete_row(doc_id, key)
    return {"deleted": deleted_count}


@router.post("/{doc_id}/row/{key:path}/restore")
async def restore_row_chunk(doc_id: str, key: str):
    tags_doc = tags_store.load(doc_id)
    if key in tags_doc.rows and (tags_doc.rows[key].excluded or tags_doc.rows[key].is_noise):
        updated_tag = tags_doc.rows[key].model_copy(update={"excluded": False, "is_noise": False})
        tags_store.set_row(doc_id, key, updated_tag)
        vector_store.sync_row_tag(doc_id, key, updated_tag)
    restored_count = vector_store.restore_chunk_by_row(doc_id, key)
    return {"restored": restored_count}


@router.put("/{doc_id}/row/{key:path}", response_model=DocTags)
async def set_row_tag(doc_id: str, key: str, tag: RowTag):
    previous_doc = tags_store.load(doc_id)
    previous = previous_doc.rows.get(key, RowTag())
    updated = tags_store.set_row(doc_id, key, tag)
    saved = updated.rows.get(key, tag)
    if saved:
        taxonomy_store.ensure_from_row_tag(saved)
        _record_feedback(doc_id, key, previous, saved)
        _record_structured_feedback(doc_id, key, previous, saved)
        vector_store.sync_row_tag(doc_id, key, saved)
    return updated


def _record_feedback(doc_id: str, row_key: str, before: RowTag, after: RowTag) -> None:
    if before.model_dump() == after.model_dump():
        return
    payload = {
        "row_id": f"{doc_id}::{row_key}",
        "doc_id": doc_id,
        "row_key": row_key,
        "before": before.model_dump(),
        "after": after.model_dump(),
        "note": after.feedback_note,
    }
    with _FEEDBACK_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _record_structured_feedback(doc_id: str, row_key: str, before: RowTag, after: RowTag) -> None:
    if not _should_record_structured_feedback(before, after):
        return

    prediction = taxonomy_store.get_prediction(f"{doc_id}::{row_key}") or {}
    predicted_category = (
        prediction.get("predicted_category")
        or before.taxonomy_category
        or before.category_tag
        or after.taxonomy_category
        or after.category_tag
    )
    predicted_subcategory = prediction.get("predicted_subcategory") or before.taxonomy_subcategory
    predicted_tags = (
        prediction.get("predicted_tags")
        or before.taxonomy_tags
        or before.detail_tags
        or after.taxonomy_tags
        or after.detail_tags
    )
    taxonomy_store.save_feedback(TaxonomyFeedbackRequest(
        row_id=f"{doc_id}::{row_key}",
        predicted_category=predicted_category,
        predicted_subcategory=predicted_subcategory,
        predicted_tags=predicted_tags or [],
        final_category=after.taxonomy_category or after.category_tag,
        final_subcategory=after.taxonomy_subcategory,
        final_tags=after.taxonomy_tags or after.detail_tags,
        action="edit" if _taxonomy_changed(before, after) else "approve",
        rationale=after.feedback_note or after.review_reason or after.rationale or None,
    ))


def _taxonomy_changed(before: RowTag, after: RowTag) -> bool:
    return (
        (before.taxonomy_category or before.category_tag) != (after.taxonomy_category or after.category_tag)
        or before.taxonomy_subcategory != after.taxonomy_subcategory
        or (before.taxonomy_tags or before.detail_tags) != (after.taxonomy_tags or after.detail_tags)
    )


def _should_record_structured_feedback(before: RowTag, after: RowTag) -> bool:
    if before.model_dump() == after.model_dump():
        return False
    if _taxonomy_changed(before, after):
        return True
    if before.review_required and not after.review_required:
        return True
    if before.review_reason != after.review_reason and str(after.review_reason or "").strip():
        return True
    if before.feedback_note != after.feedback_note and str(after.feedback_note or "").strip():
        return True
    return False


def _read_feedback() -> list[dict]:
    if not _FEEDBACK_PATH.exists():
        return []
    items = []
    for line in _FEEDBACK_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return items


def _distill(items: list[dict]) -> dict:
    by_pair: dict[tuple[str, str], int] = {}
    detail_by_category: dict[str, Counter[str]] = defaultdict(Counter)
    category_by_detail: dict[str, Counter[str]] = defaultdict(Counter)
    cue_by_category: dict[str, Counter[str]] = defaultdict(Counter)
    examples = []
    for item in items:
        before = item.get("before") or {}
        after = item.get("after") or {}
        pair = (str(before.get("category_tag") or before.get("taxonomy_category") or ""),
                str(after.get("category_tag") or after.get("taxonomy_category") or ""))
        by_pair[pair] = by_pair.get(pair, 0) + 1
        final_category = pair[1]
        detail_tags = _clean_detail_tags(after.get("detail_tags") or after.get("taxonomy_tags") or [])
        for tag in detail_tags:
            if final_category:
                detail_by_category[final_category][tag] += 1
                category_by_detail[tag][final_category] += 1
        for cue in _extract_feedback_cues(item.get("note") or after.get("review_reason") or after.get("rationale") or ""):
            if final_category:
                cue_by_category[final_category][cue] += 1
        if len(examples) < 8:
            examples.append({
                "row_id": item.get("row_id"),
                "from": pair[0],
                "to": pair[1],
                "detail_tags": detail_tags,
                "note": item.get("note") or after.get("review_reason") or "",
            })
    rules = []
    for (before, after), count in sorted(by_pair.items(), key=lambda kv: kv[1], reverse=True):
        if before == after or not after:
            continue
        rules.append(f"When rows were previously tagged as {before or 'unclassified'}, reviewers often corrected them to {after} ({count} times).")
    for category, counter in sorted(detail_by_category.items()):
        tags = [tag for tag, _count in counter.most_common(5)]
        if tags:
            rules.append(f"For {category} rows, reviewers often used detail tags: {', '.join(tags)}.")
    for detail_tag, counter in sorted(category_by_detail.items()):
        category, count = counter.most_common(1)[0]
        if count >= 2:
            rules.append(f"When detail tag '{detail_tag}' appears, reviewers most often classify the row as {category} ({count} times).")
    for category, counter in sorted(cue_by_category.items()):
        cues = [cue for cue, count in counter.most_common(5) if count >= 1]
        if cues:
            rules.append(f"Reviewer notes that mention {', '.join(cues)} often map to {category}.")
    return {
        "rules": rules[:12],
        "examples": examples,
        "total_feedback": len(items),
    }


def _clean_detail_tags(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    cleaned = []
    for value in values:
        text = str(value or "").strip()
        if text:
            cleaned.append(text)
    return list(dict.fromkeys(cleaned))[:5]


def _clean_single_tag(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _standard_detail_tags() -> set[str]:
    return {tag for tags in _TAG_TAXONOMY.values() for tag in tags}


def _is_active_issue_row(row: RowTag) -> bool:
    if row.excluded or row.is_noise:
        return False
    if str(row.is_issue or "").strip().lower() == "no":
        return False
    return bool(row.category_tag or row.taxonomy_category or row.detail_tags or row.taxonomy_tags)


def _active_detail_tag_stats() -> tuple[int, int]:
    standard = _standard_detail_tags()
    active_tags: set[str] = set()
    active_loose_tags: set[str] = set()
    for doc_tags in tags_store.iter_all():
        for row in doc_tags.rows.values():
            if not _is_active_issue_row(row):
                continue
            for tag in _clean_detail_tags(row.detail_tags or row.taxonomy_tags):
                active_tags.add(tag)
                if tag not in standard:
                    active_loose_tags.add(tag)
    return len(active_tags), len(active_loose_tags)


def _detail_tag_candidates() -> list[TagCandidate]:
    standard = _standard_detail_tags()
    counts: Counter[str] = Counter()
    categories: dict[str, Counter[str]] = defaultdict(Counter)
    for doc_tags in tags_store.iter_all():
        for row in doc_tags.rows.values():
            if not _is_active_issue_row(row):
                continue
            category = row.category_tag or row.taxonomy_category or ("Noise" if row.is_noise else "")
            for tag in _clean_detail_tags(row.detail_tags or row.taxonomy_tags):
                if tag in standard:
                    continue
                counts[tag] += 1
                if category:
                    categories[tag][category] += 1
    return [
        TagCandidate(tag=tag, count=count, categories=dict(categories[tag]))
        for tag, count in counts.most_common()
    ]


def _replace_detail_tag(values: list[str], from_tag: str, to_tag: str) -> list[str]:
    replaced = [to_tag if item == from_tag else item for item in values]
    return list(dict.fromkeys(item for item in replaced if item))[:5]


def _merge_row_detail_tag(row: RowTag, from_tag: str, to_tag: str, category: str) -> RowTag:
    detail_tags = _clean_detail_tags(row.detail_tags or row.taxonomy_tags)
    taxonomy_tags = _clean_detail_tags(row.taxonomy_tags or row.detail_tags)
    if from_tag not in detail_tags and from_tag not in taxonomy_tags:
        return row

    update = {
        "detail_tags": _replace_detail_tag(detail_tags, from_tag, to_tag),
        "taxonomy_tags": _replace_detail_tag(taxonomy_tags, from_tag, to_tag),
    }
    if category == "Noise":
        update.update({
            "excluded": True,
            "is_noise": True,
            "review_required": False,
            "review_reason": row.review_reason or "Mapped into Noise by tag taxonomy.",
        })
    elif category:
        update.update({
            "tags": [category],
            "category_tag": category,
            "taxonomy_category": category,
        })
    return row.model_copy(update=update)


def _extract_feedback_cues(text: str) -> list[str]:
    tokens = re.findall(r"[a-z][a-z0-9_-]{2,}", str(text or "").lower())
    stopwords = {
        "the", "and", "for", "this", "that", "with", "should", "would", "could",
        "row", "rows", "tag", "tags", "tagged", "category", "review", "reviewer",
        "human", "confirmed", "corrected", "instead", "lean", "leans", "issue",
        "issues", "not", "from", "into", "when", "often", "because", "after",
    }
    return list(dict.fromkeys(token for token in tokens if token not in stopwords))[:8]


# === Batch Operations ===

class BatchDeleteRequest(BaseModel):
    items: list[dict]  # [{"doc_id": "...", "row_key": "..."}, ...]


class BatchDeleteResponse(BaseModel):
    total: int
    deleted: int
    failed: list[dict]


@router.post("/batch-delete", response_model=BatchDeleteResponse)
async def batch_delete_rows(req: BatchDeleteRequest):
    """批量标记行为噪音，不进入搜索，但保留可见。"""
    total = len(req.items)
    deleted = 0
    failed = []

    for item in req.items:
        doc_id = item.get("doc_id")
        row_key = item.get("row_key")

        if not doc_id or not row_key:
            failed.append({"doc_id": doc_id, "row_key": row_key, "reason": "Missing doc_id or row_key"})
            continue

        try:
            _mark_row_noise(doc_id, row_key)
            deleted += 1
        except Exception as e:
            failed.append({"doc_id": doc_id, "row_key": row_key, "reason": str(e)})

    return BatchDeleteResponse(total=total, deleted=deleted, failed=failed)


class BatchUpdateRequest(BaseModel):
    items: list[dict]  # [{"doc_id": "...", "row_key": "...", "tag": {...}}, ...]


class BatchUpdateResponse(BaseModel):
    total: int
    updated: int
    failed: list[dict]


@router.post("/batch-update", response_model=BatchUpdateResponse)
async def batch_update_tags(req: BatchUpdateRequest):
    """批量更新行标签"""
    total = len(req.items)
    updated = 0
    failed = []

    for item in req.items:
        doc_id = item.get("doc_id")
        row_key = item.get("row_key")
        tag_data = item.get("tag")

        if not doc_id or not row_key or not tag_data:
            failed.append({"doc_id": doc_id, "row_key": row_key, "reason": "Missing required fields"})
            continue

        try:
            tag = RowTag(**tag_data)
            saved_doc = tags_store.set_row(doc_id, row_key, tag)
            saved_tag = saved_doc.rows.get(row_key, tag)
            taxonomy_store.ensure_from_row_tag(saved_tag)
            vector_store.sync_row_tag(doc_id, row_key, saved_tag)
            updated += 1
        except Exception as e:
            failed.append({"doc_id": doc_id, "row_key": row_key, "reason": str(e)})

    return BatchUpdateResponse(total=total, updated=updated, failed=failed)
