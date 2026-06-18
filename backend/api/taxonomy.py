from fastapi import APIRouter

from ..models.taxonomy import (
    TaxonomyDeactivateRequest,
    TaxonomyMergeRequest,
    TaxonomyNode,
    TaxonomyRenameRequest,
    TaxonomyFeedbackRequest,
    TaxonomyFeedbackApplySimilarRequest,
)
from ..services import tags_store, taxonomy_store, vector_store


router = APIRouter(prefix="/taxonomy", tags=["taxonomy"])


def _sync_updates(updates: list[dict]) -> int:
    synced = 0
    for item in updates:
        doc_id = item["doc_id"]
        doc_tags = tags_store.load(doc_id)
        for row_key in item["rows"]:
            tag = doc_tags.rows.get(row_key)
            if tag:
                synced += vector_store.sync_row_tag(doc_id, row_key, tag)
    return synced


@router.get("")
async def get_taxonomy():
    return {
        "taxonomy": taxonomy_store.load(),
        "candidates": taxonomy_store.candidates(),
    }


@router.post("/nodes")
async def upsert_node(node: TaxonomyNode):
    return taxonomy_store.upsert_node(node)


@router.post("/merge")
async def merge_taxonomy(req: TaxonomyMergeRequest):
    store = taxonomy_store.merge(
        req.from_category,
        req.from_subcategory,
        req.to_category,
        req.to_subcategory,
    )
    updates = taxonomy_store.rewrite_all_row_tags()
    return {"taxonomy": store, "updates": updates, "synced": _sync_updates(updates)}


@router.post("/rename")
async def rename_taxonomy(req: TaxonomyRenameRequest):
    store = taxonomy_store.rename(
        req.category,
        req.subcategory,
        req.new_category,
        req.new_subcategory,
    )
    updates = taxonomy_store.rewrite_all_row_tags()
    return {"taxonomy": store, "updates": updates, "synced": _sync_updates(updates)}


@router.post("/deactivate")
async def deactivate_taxonomy(req: TaxonomyDeactivateRequest):
    return taxonomy_store.deactivate(req.category, req.subcategory)


@router.post("/apply-mappings")
async def apply_mappings():
    updates = taxonomy_store.rewrite_all_row_tags()
    return {"updates": updates, "synced": _sync_updates(updates)}


@router.post("/canonicalize")
async def canonicalize_taxonomy():
    updates = taxonomy_store.canonicalize_all_row_tags()
    return {"updates": updates, "synced": _sync_updates(updates), "categories": taxonomy_store.CANONICAL_CATEGORIES}


@router.post("/normalize-subcategories")
async def normalize_subcategories():
    updates = taxonomy_store.normalize_all_subcategories()
    return {
        "updates": updates,
        "synced": _sync_updates(updates),
        "subcategories": taxonomy_store.STANDARD_SUBCATEGORIES,
    }


@router.post("/feedback")
async def submit_feedback(req: TaxonomyFeedbackRequest):
    taxonomy_store.save_feedback(req)
    return {"status": "ok"}


@router.post("/feedback/apply-similar")
async def apply_feedback_to_similar(req: TaxonomyFeedbackApplySimilarRequest):
    count = taxonomy_store.apply_feedback_to_similar(req)
    return {"status": "ok", "affected_rows": count}


@router.get("/feedback/metrics")
async def get_feedback_metrics():
    return taxonomy_store.get_feedback_metrics()
