from collections import Counter
from pydantic import BaseModel, Field

from ..config import settings
from ..models.taxonomy import (
    TaxonomyNode,
    TaxonomyStore,
    TaxonomyFeedbackRequest,
    TaxonomyFeedbackApplySimilarRequest,
)
from ..models.tags import DocTags, RowTag
from . import tags_store
from .duck_lance_store import duck


_PATH = settings.taxonomy_path
_ROW_TAG_DIR = settings.row_tags_dir
CANONICAL_CATEGORIES = ("Translation", "Voice Over", "Animation", "Source")
STANDARD_SUBCATEGORIES = {
    "Animation": (
        "Validation",
        "Post Editing",
        "UI Capture",
        "Motion Timing",
        "Layout",
    ),
    "Translation": (
        "Validation",
        "Terminology",
        "Locale Difference",
        "UI Text",
        "Instructions",
    ),
    "Voice Over": (
        "Validation",
        "Script Mismatch",
        "Audio Quality",
        "Pronunciation",
        "Pacing",
        "Retake",
    ),
    "Source": (
        "Validation",
        "Source Mismatch",
        "Guidance",
        "Locale Difference",
        "Source Asset",
    ),
}

STANDARD_SMALL_TAGS = (
    "validation", "terminology", "locale difference", "ui text", "instructions",
    "script mismatch", "audio quality", "pronunciation", "pacing", "retake",
    "post editing", "ui capture", "motion timing", "layout",
    "source mismatch", "guidance", "source asset",
)


def _key(category: str, subcategory: str = "") -> str:
    return f"{category.strip()} > {subcategory.strip()}".strip(" >")


def load() -> TaxonomyStore:
    if not _PATH.exists():
        return TaxonomyStore()
    return TaxonomyStore.model_validate_json(_PATH.read_text(encoding="utf-8"))


def save(store: TaxonomyStore) -> TaxonomyStore:
    _PATH.write_text(store.model_dump_json(indent=2), encoding="utf-8")
    return store


def _find_node(store: TaxonomyStore, category: str, subcategory: str = "") -> TaxonomyNode | None:
    for node in store.nodes:
        if node.category == category and node.subcategory == subcategory:
            return node
    return None


def upsert_node(node: TaxonomyNode) -> TaxonomyStore:
    store = load()
    existing = _find_node(store, node.category, node.subcategory)
    if existing:
        existing.tags = sorted(set(existing.tags) | set(node.tags))
        existing.description = node.description or existing.description
        existing.active = node.active
        existing.aliases = sorted(set(existing.aliases) | set(node.aliases))
    else:
        store.nodes.append(node)
    store.version += 1
    store.nodes.sort(key=lambda n: (n.category.lower(), n.subcategory.lower()))
    return save(store)


def ensure_from_row_tag(tag: RowTag) -> None:
    if not tag.taxonomy_category:
        return
    upsert_node(TaxonomyNode(
        category=tag.taxonomy_category,
        subcategory=tag.taxonomy_subcategory,
        tags=tag.taxonomy_tags,
    ))


def normalize(category: str, subcategory: str = "") -> tuple[str, str]:
    store = load()
    key = _key(category, subcategory)
    mapped = store.mappings.get(key)
    if not mapped:
        if category in CANONICAL_CATEGORIES:
            return category, subcategory
        return canonical_category_for_text(category, subcategory), subcategory
    if " > " in mapped:
        return tuple(mapped.split(" > ", 1))  # type: ignore[return-value]
    return mapped, ""


def canonical_category_for_text(category: str, subcategory: str = "", tags: list[str] | None = None, rationale: str = "", dept_tags: list[str] | None = None) -> str:
    dept = {tag.strip().lower() for tag in dept_tags or []}
    text = " ".join([category, subcategory, " ".join(tags or []), rationale]).lower()

    voice_terms = (
        "voiceover", "voice over", " vo", "narration", "pronunciation", "pacing", "pause",
        "recording", "audio", "noise", "mouth", "sfx", "subtitle timing",
    )
    animation_terms = (
        "animation", "motion", "visual", "layout", "graphic", "transition", "fade", "icon",
        "screen", "device", "alignment", "position", "zoom", "scale", "render", "frame",
    )
    translation_terms = (
        "translation", "terminology", "copy", "locale", "localization", "subtitle", "title",
        "punctuation", "format", "text", "truncat", "grammar", "spelling", "font", "string",
        "language", "regional",
    )
    source_terms = (
        "source", "upstream", "reference", "capture", "screenshot", "asset", "data",
        "discrepancy", "contact", "email", "placeholder", "file", "administrative",
    )

    if "motion" in dept:
        return "Animation"
    if "copy" in dept:
        return "Translation"
    if any(term in text for term in voice_terms):
        return "Voice Over"
    if any(term in text for term in animation_terms):
        return "Animation"
    if any(term in text for term in translation_terms):
        return "Translation"
    if "source" in dept or any(term in text for term in source_terms):
        return "Source"
    return "Source"


def standard_subcategory_for_text(category: str, subcategory: str = "", tags: list[str] | None = None, rationale: str = "") -> str:
    text = " ".join([subcategory, " ".join(tags or []), rationale]).lower()
    if category == "Animation":
        if any(term in text for term in ("glitch", "choppy", "frozen", "stutter", "jitter", "lag", "playback")):
            return "Post Editing"
        if any(term in text for term in ("timing", "sync", "delay", "early", "late", "sfx", "voiceover", "audio")):
            return "Motion Timing"
        if any(term in text for term in ("transition", "fade", "missing animation", "missing transition")):
            return "Motion Timing"
        if any(term in text for term in ("layout", "position", "align", "overlap", "placement", "closer", "spacing")):
            return "Layout"
        if any(term in text for term in ("asset", "source", "reference", "mismatch", "incorrect visual", "wrong visual")):
            return "Validation"
        if any(term in text for term in ("icon", "button", "touch", "dot", "ui element", "screen text")):
            return "UI Capture"
        if any(term in text for term in ("render", "frame", "artifact", "drop-shadow", "shadow", "mask")):
            return "Post Editing"
        if any(term in text for term in ("duration", "hold", "pause", "extend", "shorten")):
            return "Motion Timing"
        return "Validation"

    if category == "Translation":
        if any(term in text for term in ("terminology", "term", "brand", "siri", "wi-fi", "wlan", "consistency")):
            return "Terminology"
        if any(term in text for term in ("title", "heading", "thumbnail", "headline")):
            return "UI Text"
        if any(term in text for term in ("subtitle", "vtt", "caption", "timestamp", "line break")):
            return "UI Text"
        if any(term in text for term in ("punctuation", "quotation", "format", "date", "time", "number", "capitalization")):
            return "Validation"
        if any(term in text for term in ("locale", "regional", "wording", "zhcn", "jajp", "ptbr", "frfr", "frca", "dede", "engb")):
            return "Locale Difference"
        if any(term in text for term in ("ui text", "copy", "translation", "grammar", "spelling", "string")):
            return "UI Text"
        if any(term in text for term in ("truncat", "overflow", "fit", "font", "text overlap")):
            return "UI Text"
        if any(term in text for term in ("placeholder", "sample", "mock", "email", "contact", "name")):
            return "Instructions"
        return "Validation"

    if category == "Voice Over":
        if any(term in text for term in ("pace", "pacing", "pause", "rhythm", "speed", "too fast", "too slow")):
            return "Pacing"
        if any(term in text for term in ("pronunciation", "pronounce", "intonation", "accent", "tone")):
            return "Pronunciation"
        if any(term in text for term in ("noise", "mouth", "click", "pop", "recording", "audio quality")):
            return "Audio Quality"
        if any(term in text for term in ("sync", "animation", "timing", "sfx", "screen")):
            return "Validation"
        if any(term in text for term in ("script", "text mismatch", "vo text", "line mismatch")):
            return "Script Mismatch"
        if any(term in text for term in ("mix", "music", "volume", "level", "sfx")):
            return "Audio Quality"
        return "Validation"

    if category == "Source":
        if any(term in text for term in ("asset", "mismatch", "wrong", "incorrect", "visual")):
            return "Source Mismatch"
        if any(term in text for term in ("reference", "capture", "screenshot", "true ui")):
            return "Source Mismatch"
        if any(term in text for term in ("upstream", "source bug", "content error", "od source")):
            return "Source Mismatch"
        if any(term in text for term in ("placeholder", "mock", "sample", "email", "contact", "name")):
            return "Guidance"
        if any(term in text for term in ("file", "version", "update", "administrative", "notification")):
            return "Source Asset"
        return "Validation"

    return subcategory or "Other"


def merge(from_category: str, from_subcategory: str, to_category: str, to_subcategory: str) -> TaxonomyStore:
    store = load()
    from_key = _key(from_category, from_subcategory)
    to_key = _key(to_category, to_subcategory)
    store.mappings[from_key] = to_key
    from_node = _find_node(store, from_category, from_subcategory)
    to_node = _find_node(store, to_category, to_subcategory)
    if from_node:
        from_node.active = False
        from_node.aliases = sorted(set(from_node.aliases) | {to_key})
    if not to_node:
        store.nodes.append(TaxonomyNode(category=to_category, subcategory=to_subcategory))
    store.version += 1
    return save(store)


def rename(category: str, subcategory: str, new_category: str, new_subcategory: str) -> TaxonomyStore:
    store = load()
    node = _find_node(store, category, subcategory)
    if node:
        node.category = new_category
        node.subcategory = new_subcategory
    store.mappings[_key(category, subcategory)] = _key(new_category, new_subcategory)
    store.version += 1
    return save(store)


def deactivate(category: str, subcategory: str = "") -> TaxonomyStore:
    store = load()
    node = _find_node(store, category, subcategory)
    if node:
        node.active = False
        store.version += 1
        return save(store)
    return store


def candidates() -> list[dict]:
    counts: Counter[tuple[str, str]] = Counter()
    tags: dict[tuple[str, str], Counter[str]] = {}
    examples: dict[tuple[str, str], list[dict]] = {}
    for path in _ROW_TAG_DIR.glob("*.json"):
        try:
            doc_tags = DocTags.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for row_key, row in doc_tags.rows.items():
            if not row.taxonomy_category:
                continue
            key = (row.taxonomy_category, row.taxonomy_subcategory)
            counts[key] += 1
            tags.setdefault(key, Counter()).update(row.taxonomy_tags)
            examples.setdefault(key, []).append({
                "doc_id": doc_tags.doc_id,
                "row_key": row_key,
                "confidence": row.taxonomy_confidence,
                "rationale": row.taxonomy_rationale,
            })
    return [
        {
            "category": category,
            "subcategory": subcategory,
            "count": count,
            "tags": [tag for tag, _count in tags.get((category, subcategory), Counter()).most_common(12)],
            "examples": examples.get((category, subcategory), [])[:5],
        }
        for (category, subcategory), count in sorted(counts.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))
    ]


def rewrite_all_row_tags() -> list[dict]:
    updates = []
    store = load()
    if not store.mappings:
        return updates

    for path in _ROW_TAG_DIR.glob("*.json"):
        try:
            doc_tags = DocTags.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        changed = False
        changed_rows = []
        for row_key, row in doc_tags.rows.items():
            current_key = _key(row.taxonomy_category, row.taxonomy_subcategory)
            mapped = store.mappings.get(current_key)
            if not mapped:
                continue
            if " > " in mapped:
                category, subcategory = mapped.split(" > ", 1)
            else:
                category, subcategory = mapped, ""
            if category == row.taxonomy_category and subcategory == row.taxonomy_subcategory:
                continue
            doc_tags.rows[row_key] = row.model_copy(update={
                "taxonomy_category": category,
                "taxonomy_subcategory": subcategory,
            })
            changed = True
            changed_rows.append(row_key)
        if changed:
            path.write_text(doc_tags.model_dump_json(indent=2), encoding="utf-8")
            updates.append({"doc_id": doc_tags.doc_id, "rows": changed_rows})
    return updates


def canonicalize_all_row_tags() -> list[dict]:
    updates = []
    for path in _ROW_TAG_DIR.glob("*.json"):
        try:
            doc_tags = DocTags.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        changed_rows = []
        for row_key, row in doc_tags.rows.items():
            if not row.taxonomy_category:
                continue
            canonical = canonical_category_for_text(
                row.taxonomy_category,
                row.taxonomy_subcategory,
                row.taxonomy_tags,
                row.taxonomy_rationale,
                row.tags,
            )
            if row.taxonomy_category == canonical:
                continue
            doc_tags.rows[row_key] = row.model_copy(update={"taxonomy_category": canonical})
            changed_rows.append(row_key)
        if changed_rows:
            path.write_text(doc_tags.model_dump_json(indent=2), encoding="utf-8")
            updates.append({"doc_id": doc_tags.doc_id, "rows": changed_rows})

    store = load()
    for category in CANONICAL_CATEGORIES:
        if not _find_node(store, category, ""):
            store.nodes.append(TaxonomyNode(category=category))
    store.nodes = [
        node for node in store.nodes
        if node.category in CANONICAL_CATEGORIES or not node.active
    ]
    store.version += 1
    save(store)
    return updates


def normalize_all_subcategories() -> list[dict]:
    updates = []
    for path in _ROW_TAG_DIR.glob("*.json"):
        try:
            doc_tags = DocTags.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        changed_rows = []
        for row_key, row in doc_tags.rows.items():
            if not row.taxonomy_category:
                continue
            category = row.taxonomy_category if row.taxonomy_category in CANONICAL_CATEGORIES else canonical_category_for_text(
                row.taxonomy_category,
                row.taxonomy_subcategory,
                row.taxonomy_tags,
                row.taxonomy_rationale,
                row.tags,
            )
            standard = standard_subcategory_for_text(
                category,
                row.taxonomy_subcategory,
                row.taxonomy_tags,
                row.taxonomy_rationale,
            )
            if row.taxonomy_category == category and row.taxonomy_subcategory == standard:
                continue
            doc_tags.rows[row_key] = row.model_copy(update={
                "taxonomy_category": category,
                "taxonomy_subcategory": standard,
            })
            changed_rows.append(row_key)
        if changed_rows:
            path.write_text(doc_tags.model_dump_json(indent=2), encoding="utf-8")
            updates.append({"doc_id": doc_tags.doc_id, "rows": changed_rows})

    store = load()
    new_nodes = []
    for category, subcategories in STANDARD_SUBCATEGORIES.items():
        for subcategory in subcategories:
            existing = _find_node(store, category, subcategory)
            if existing:
                new_nodes.append(existing)
            else:
                new_nodes.append(TaxonomyNode(category=category, subcategory=subcategory))
    store.nodes = new_nodes
    store.version += 1
    save(store)
    return updates


def _split_row_id(row_id: str) -> tuple[str | None, str | None]:
    if "::" not in row_id:
        return None, None
    doc_id, row_key = row_id.split("::", 1)
    if not doc_id or not row_key:
        return None, None
    return doc_id, row_key


def _find_chunk_row_ref(row_id: str) -> tuple[str | None, str | None]:
    doc_id, row_key = _split_row_id(row_id)
    if doc_id and row_key:
        row = duck().execute(
            "SELECT doc_id, row_key FROM chunks WHERE doc_id = ? AND row_key = ?",
            (doc_id, row_key),
        ).fetchone()
        if row:
            return row[0], row[1]

    row = duck().execute(
        "SELECT doc_id, row_key FROM chunks WHERE chunk_id = ? OR row_key = ?",
        (row_id, row_id),
    ).fetchone()
    if row:
        return row[0], row[1]
    return doc_id, row_key


def _persist_feedback_row_tag(
    row_id: str,
    final_category: str,
    final_subcategory: str,
    final_tags: list[str],
    action: str,
    rationale: str,
) -> bool:
    doc_id, row_key = _find_chunk_row_ref(row_id)
    if not doc_id or not row_key:
        return False

    existing = tags_store.load(doc_id).rows.get(row_key, RowTag())
    if action == "reject":
        updated = existing.model_copy(update={
            "taxonomy_category": "",
            "taxonomy_subcategory": "",
            "taxonomy_tags": [],
            "taxonomy_confidence": 0.0,
            "taxonomy_rationale": rationale or existing.taxonomy_rationale,
        })
    else:
        updated = existing.model_copy(update={
            "taxonomy_category": final_category,
            "taxonomy_subcategory": final_subcategory,
            "taxonomy_tags": final_tags or existing.taxonomy_tags,
            "taxonomy_confidence": 1.0,
            "taxonomy_rationale": rationale or existing.taxonomy_rationale,
        })

    tags_store.set_row(doc_id, row_key, updated)

    from . import vector_store
    vector_store.sync_row_tag(doc_id, row_key, updated)
    return True


def save_prediction(
    row_id: str,
    predicted_category: str,
    predicted_subcategory: str,
    predicted_tags: list[str],
    confidence: float,
    rationale: str,
):
    """Save a taxonomy prediction."""
    tags_str = ",".join(predicted_tags) if predicted_tags else ""
    duck().execute(
        """
        INSERT INTO taxonomy_predictions
        (row_id, predicted_category, predicted_subcategory, predicted_tags, confidence, rationale)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (row_id) DO UPDATE SET
            predicted_category = excluded.predicted_category,
            predicted_subcategory = excluded.predicted_subcategory,
            predicted_tags = excluded.predicted_tags,
            confidence = excluded.confidence,
            rationale = excluded.rationale,
            created_at = now()
        """,
        (
            row_id,
            predicted_category,
            predicted_subcategory,
            tags_str,
            confidence,
            rationale,
        ),
    )


def get_prediction(row_id: str) -> dict | None:
    row = duck().execute(
        """
        SELECT predicted_category, predicted_subcategory, predicted_tags, confidence, rationale
        FROM taxonomy_predictions
        WHERE row_id = ?
        """,
        (row_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "predicted_category": row[0] or "",
        "predicted_subcategory": row[1] or "",
        "predicted_tags": [tag for tag in (row[2] or "").split(",") if tag],
        "confidence": float(row[3] or 0.0),
        "rationale": row[4] or "",
    }


def save_feedback(req: TaxonomyFeedbackRequest):
    """Save user feedback on a taxonomy prediction."""
    predicted_tags_str = ",".join(req.predicted_tags) if req.predicted_tags else ""
    final_tags_str = ",".join(req.final_tags) if req.final_tags else ""

    duck().execute(
        """
        INSERT INTO taxonomy_feedback
        (row_id, predicted_category, predicted_subcategory, predicted_tags,
         final_category, final_subcategory, final_tags, action, reviewer, rationale)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (row_id) DO UPDATE SET
            predicted_category = excluded.predicted_category,
            predicted_subcategory = excluded.predicted_subcategory,
            predicted_tags = excluded.predicted_tags,
            final_category = excluded.final_category,
            final_subcategory = excluded.final_subcategory,
            final_tags = excluded.final_tags,
            action = excluded.action,
            reviewer = excluded.reviewer,
            rationale = excluded.rationale,
            review_time = now()
        """,
        (
            req.row_id,
            req.predicted_category,
            req.predicted_subcategory,
            predicted_tags_str,
            req.final_category,
            req.final_subcategory,
            final_tags_str,
            req.action,
            req.reviewer,
            req.rationale,
        ),
    )

    _persist_feedback_row_tag(
        row_id=req.row_id,
        final_category=req.final_category,
        final_subcategory=req.final_subcategory,
        final_tags=req.final_tags,
        action=req.action,
        rationale=req.rationale,
    )


def apply_feedback_to_similar(req: TaxonomyFeedbackApplySimilarRequest) -> int:
    """Find issues with same predicted categories and apply the same fix."""
    # 1. Get the original prediction for this row
    row = duck().execute("SELECT predicted_category, predicted_subcategory FROM taxonomy_predictions WHERE row_id = ?", (req.row_id,)).fetchone()
    if not row:
        # Fallback to current chunk info if not in predictions
        row = duck().execute(
            "SELECT taxonomy_category, taxonomy_subcategory FROM chunks WHERE chunk_id = ? OR row_key = ?",
            (req.row_id, req.row_id),
        ).fetchone()

    if not row:
        return 0

    orig_cat, orig_sub = row[0], row[1]

    source_doc_id, source_row_key = _find_chunk_row_ref(req.row_id)
    affected_rows = duck().execute(
        """
        SELECT doc_id, row_key
        FROM chunks
        WHERE taxonomy_category = ? AND taxonomy_subcategory = ? AND taxonomy_confidence < 0.90
        """,
        (orig_cat, orig_sub),
    ).fetchall()

    count = 0
    final_tags_str = ",".join(req.final_tags) if req.final_tags else ""
    for doc_id, row_key in affected_rows:
        if source_doc_id and source_row_key and doc_id == source_doc_id and row_key == source_row_key:
            continue

        row_id = f"{doc_id}::{row_key}"
        if not _persist_feedback_row_tag(
            row_id=row_id,
            final_category=req.final_category,
            final_subcategory=req.final_subcategory,
            final_tags=req.final_tags,
            action="edit",
            rationale=req.rationale,
        ):
            continue

        duck().execute(
            """
            INSERT INTO taxonomy_feedback
            (row_id, predicted_category, predicted_subcategory, predicted_tags,
             final_category, final_subcategory, final_tags, action, reviewer, rationale)
            VALUES (?, ?, ?, '', ?, ?, ?, 'auto-apply', ?, ?)
            ON CONFLICT (row_id) DO UPDATE SET
                predicted_category = excluded.predicted_category,
                predicted_subcategory = excluded.predicted_subcategory,
                final_category = excluded.final_category,
                final_subcategory = excluded.final_subcategory,
                final_tags = excluded.final_tags,
                action = excluded.action,
                reviewer = excluded.reviewer,
                rationale = excluded.rationale,
                review_time = now()
            """,
            (
                row_id,
                orig_cat,
                orig_sub,
                req.final_category,
                req.final_subcategory,
                final_tags_str,
                req.reviewer,
                f"Auto-applied from row {req.row_id}: {req.rationale}",
            ),
        )
        count += 1

    return count


def get_feedback_metrics() -> dict:
    """Return dashboard metrics for taxonomy feedback."""
    stats = duck().execute(
        """
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN action = 'approve' THEN 1 ELSE 0 END) as approved,
            SUM(CASE WHEN action = 'edit' THEN 1 ELSE 0 END) as edited,
            SUM(CASE WHEN action = 'reject' THEN 1 ELSE 0 END) as rejected
        FROM taxonomy_feedback
        WHERE action IN ('approve', 'edit', 'reject')
        """
    ).fetchone()

    total = stats[0] or 0
    approved = stats[1] or 0
    edited = stats[2] or 0
    rejected = stats[3] or 0

    approval_rate = (approved / total * 100) if total > 0 else 0.0
    edit_rate = (edited / total * 100) if total > 0 else 0.0
    reject_rate = (rejected / total * 100) if total > 0 else 0.0

    low_confidence = duck().execute(
        """
        SELECT chunk_id, title, text, taxonomy_category, taxonomy_subcategory, taxonomy_confidence
        FROM chunks
        WHERE taxonomy_confidence < 0.90 AND taxonomy_confidence > 0.0
        AND chunk_id NOT IN (SELECT row_id FROM taxonomy_feedback)
        AND row_key NOT IN (SELECT row_id FROM taxonomy_feedback)
        ORDER BY taxonomy_confidence ASC
        LIMIT 20
        """
    ).fetchall()

    queue = [
        {
            "row_id": r[0],
            "title": r[1],
            "text": r[2],
            "category": r[3],
            "subcategory": r[4],
            "confidence": r[5]
        }
        for r in low_confidence
    ]

    accuracy_by_category = duck().execute(
        """
        SELECT
            predicted_category,
            COUNT(*) as total,
            SUM(CASE WHEN action = 'approve' THEN 1 ELSE 0 END) as approved
        FROM taxonomy_feedback
        WHERE action IN ('approve', 'edit', 'reject')
        GROUP BY predicted_category
        ORDER BY total DESC
        """
    ).fetchall()

    accuracy = {
        row[0]: {
            "total": row[1],
            "accuracy": (row[2] / row[1] * 100) if row[1] > 0 else 0.0
        }
        for row in accuracy_by_category
    }

    return {
        "total_reviews": total,
        "approval_rate": approval_rate,
        "edit_rate": edit_rate,
        "reject_rate": reject_rate,
        "per_category_accuracy": accuracy,
        "low_confidence_queue": queue
    }
