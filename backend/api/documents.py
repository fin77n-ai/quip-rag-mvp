import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional
from ..config import settings
from ..services import auto_tagger, chunker, quip_parser, rules_store, tags_store, vector_store

router = APIRouter(prefix="/documents", tags=["documents"])
logger = logging.getLogger(__name__)


class DocMetaPatch(BaseModel):
    category: Optional[str] = None
    sprint: Optional[str] = None


class ReprocessResponse(BaseModel):
    doc_id: str
    chunks: int
    issue_rows: int
    excluded_rows: int
    source_path: str


class ReprocessAllResponse(BaseModel):
    total_sources: int
    reprocessed: int
    failed: list[dict]
    docs: list[ReprocessResponse]


class ReprocessBatchRequest(BaseModel):
    doc_ids: list[str] = Field(default_factory=list)


def _reprocess_source_paths(doc_ids: list[str] | None = None):
    if doc_ids is None:
        return sorted(settings.quip_dir.glob("*.json"))

    source_by_doc_id: dict[str, Path] = {}
    for path in sorted(settings.quip_dir.glob("*.json")):
        source_by_doc_id[path.stem] = path
        try:
            raw_doc = json.loads(path.read_text(encoding="utf-8"))
            source_doc_id = str(raw_doc.get("thread_id") or "").strip()
            if source_doc_id:
                source_by_doc_id[source_doc_id] = path
        except (OSError, json.JSONDecodeError):
            continue

    return [
        source_by_doc_id.get(doc_id, settings.quip_dir / f"{doc_id}.json")
        for doc_id in dict.fromkeys(doc_ids)
    ]


def _source_doc_id(path: Path) -> str:
    if not path.exists():
        return path.stem
    try:
        raw_doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return path.stem
    return str(raw_doc.get("thread_id") or path.stem)


@router.get("")
def list_documents(category: str | None = Query(None), sprint: str | None = Query(None)):
    return {"docs": vector_store.list_docs(category=category, sprint=sprint)}


@router.get("/stats")
def collection_stats():
    return vector_store.stats()


@router.get("/sprints")
def list_sprints():
    return {"sprints": vector_store.list_sprints()}


@router.get("/{doc_id}/chunks")
async def get_chunks(doc_id: str):
    return {"chunks": vector_store.get_chunks(doc_id)}


@router.patch("/{doc_id}")
async def patch_doc_metadata(doc_id: str, patch: DocMetaPatch):
    updated = vector_store.update_doc_metadata(
        doc_id, category=patch.category, sprint=patch.sprint
    )
    return {"updated_chunks": updated}


@router.delete("/{doc_id}")
async def delete_document(doc_id: str):
    vector_store.delete_doc(doc_id)
    return {"deleted": doc_id}


async def _reprocess_document(doc_id: str) -> ReprocessResponse:
    source_path = _reprocess_source_paths([doc_id])[0]
    if not source_path.exists():
        raise HTTPException(404, f"Saved source file not found for {doc_id}")

    try:
        raw_doc = json.loads(source_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(400, f"Failed to read saved source for {doc_id}: {exc}") from exc

    # Backup existing metadata before parsing & deleting chunks
    existing_docs = vector_store.list_docs() or []
    existing_doc = next((d for d in existing_docs if d["doc_id"] == doc_id), None)
    preserved_sprint = existing_doc["sprint"] if existing_doc and existing_doc.get("sprint") else None
    preserved_category = existing_doc["category"] if existing_doc and existing_doc.get("category") else None

    rules = rules_store.load()
    await auto_tagger.auto_tag_doc(raw_doc, rules)
    parsed = quip_parser.parse_dict(raw_doc, rules)

    vector_store.delete_doc(parsed.doc_id)
    chunks = chunker.chunk_doc(parsed)
    # Restore manual metadata, falling back to parsed prefix
    category = preserved_category or parsed.prefix or "VSD"
    vector_store.upsert_chunks(chunks, category=category)
    if preserved_sprint:
        vector_store.update_doc_metadata(parsed.doc_id, sprint=preserved_sprint)

    saved_tags = tags_store.load(parsed.doc_id)
    issue_rows = 0
    excluded_rows = 0
    for chunk in chunks:
        meta = chunk.get("metadata", {})
        if str(meta.get("is_issue") or "").strip().lower() == "yes":
            issue_rows += 1
    for row in saved_tags.rows.values():
        if row.excluded:
            excluded_rows += 1

    return ReprocessResponse(
        doc_id=parsed.doc_id,
        chunks=len(chunks),
        issue_rows=issue_rows,
        excluded_rows=excluded_rows,
        source_path=str(source_path),
    )


@router.post("/{doc_id}/reprocess", response_model=ReprocessResponse)
async def reprocess_document(doc_id: str):
    return await _reprocess_document(doc_id)


@router.post("/reprocess-all", response_model=ReprocessAllResponse)
async def reprocess_all_documents():
    source_paths = sorted(settings.quip_dir.glob("*.json"))
    docs: list[ReprocessResponse] = []
    failed: list[dict] = []

    for path in source_paths:
        doc_id = path.stem
        try:
            docs.append(await _reprocess_document(doc_id))
        except HTTPException as exc:
            failed.append({"doc_id": doc_id, "reason": exc.detail})
        except Exception as exc:
            failed.append({"doc_id": doc_id, "reason": str(exc)})

    return ReprocessAllResponse(
        total_sources=len(source_paths),
        reprocessed=len(docs),
        failed=failed,
        docs=docs,
    )


@router.post("/reprocess-all/stream")
async def reprocess_all_documents_stream(req: ReprocessBatchRequest | None = None):
    async def generate_events():
        source_paths = _reprocess_source_paths(None if req is None else req.doc_ids)
        total = len(source_paths)
        processed = 0
        failed = 0
        docs: list[dict] = []
        failures: list[dict] = []

        existing_docs_map = {d["doc_id"]: d for d in (vector_store.list_docs() or [])}

        yield f"event: start\ndata: {json.dumps({'total': total})}\n\n"

        for idx, path in enumerate(source_paths, 1):
            doc_id = _source_doc_id(path)

            existing_doc = existing_docs_map.get(doc_id)
            preserved_sprint = existing_doc["sprint"] if existing_doc and existing_doc.get("sprint") else None
            preserved_category = existing_doc["category"] if existing_doc and existing_doc.get("category") else None

            try:
                source_path = path
                if not source_path.exists():
                    raise HTTPException(404, f"Saved source file not found for {doc_id}")

                yield f"event: progress\ndata: {json.dumps({'index': idx, 'total': total, 'doc_id': doc_id, 'stage': 'loading-source'})}\n\n"
                try:
                    raw_doc = json.loads(source_path.read_text(encoding='utf-8'))
                except Exception as exc:
                    raise HTTPException(400, f"Failed to read saved source for {doc_id}: {exc}") from exc

                rules = rules_store.load()
                yield f"event: progress\ndata: {json.dumps({'index': idx, 'total': total, 'doc_id': doc_id, 'stage': 'auto-tagging'})}\n\n"
                await auto_tagger.auto_tag_doc(raw_doc, rules)

                yield f"event: progress\ndata: {json.dumps({'index': idx, 'total': total, 'doc_id': doc_id, 'stage': 'parsing'})}\n\n"
                parsed = quip_parser.parse_dict(raw_doc, rules)

                yield f"event: progress\ndata: {json.dumps({'index': idx, 'total': total, 'doc_id': doc_id, 'stage': 'rebuilding-chunks'})}\n\n"
                vector_store.delete_doc(parsed.doc_id)
                chunks = chunker.chunk_doc(parsed)
                # Restore manual metadata, falling back to parsed prefix
                category = preserved_category or parsed.prefix or "VSD"
                vector_store.upsert_chunks(chunks, category=category)
                if preserved_sprint:
                    vector_store.update_doc_metadata(parsed.doc_id, sprint=preserved_sprint)

                saved_tags = tags_store.load(parsed.doc_id)
                issue_rows = 0
                excluded_rows = 0
                for chunk in chunks:
                    meta = chunk.get("metadata", {})
                    if str(meta.get("is_issue") or "").strip().lower() == "yes":
                        issue_rows += 1
                for row in saved_tags.rows.values():
                    if row.excluded:
                        excluded_rows += 1

                result = ReprocessResponse(
                    doc_id=parsed.doc_id,
                    chunks=len(chunks),
                    issue_rows=issue_rows,
                    excluded_rows=excluded_rows,
                    source_path=str(source_path),
                )
                processed += 1
                payload = result.model_dump()
                docs.append(payload)
                yield f"event: doc_complete\ndata: {json.dumps({'index': idx, 'total': total, 'doc': payload, 'processed': processed, 'failed': failed})}\n\n"
            except HTTPException as exc:
                failed += 1
                failure = {"doc_id": doc_id, "reason": exc.detail}
                failures.append(failure)
                yield f"event: error\ndata: {json.dumps({'index': idx, 'total': total, **failure, 'processed': processed, 'failed': failed})}\n\n"
            except Exception as exc:
                logger.exception("Failed to reprocess %s", doc_id)
                failed += 1
                failure = {"doc_id": doc_id, "reason": str(exc)}
                failures.append(failure)
                yield f"event: error\ndata: {json.dumps({'index': idx, 'total': total, **failure, 'processed': processed, 'failed': failed})}\n\n"

        yield f"event: complete\ndata: {json.dumps({'total_sources': total, 'reprocessed': processed, 'failed': failures, 'docs': docs})}\n\n"

    return StreamingResponse(generate_events(), media_type="text/event-stream")
