import json
import httpx
import re
import asyncio
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..models.rules import FilterRules
from ..services import auto_tagger, quip_parser, rules_store, qc as qc_service


router = APIRouter(prefix="/preprocess", tags=["preprocess"])


class PreviewRequest(BaseModel):
    """Files are uploaded separately; this carries override rules (optional)."""
    rules: FilterRules | None = None


@router.post("/preview")
async def preview(files: list[UploadFile] = File(...)):
    """Return processed structure for each uploaded JSON using saved rules.
    Frontend can re-call this after editing rules to see live preview."""
    rules = rules_store.load()
    out = []
    for f in files:
        try:
            data = json.loads(await f.read())
            preview_doc = quip_parser.preview_dict(data, rules)
            preview_doc["qc"] = qc_service.qc_preview_doc(preview_doc, rules).model_dump()
            out.append(preview_doc)
        except Exception as e:
            out.append({"doc_id": f.filename, "error": str(e)})
    return {"docs": out, "rules": rules}


@router.post("/preview-with-rules")
async def preview_with_rules(
    rules_json: str,
    files: list[UploadFile] = File(...),
):
    """Preview with ad-hoc rules (without saving to disk).
    rules_json is the JSON-encoded FilterRules object."""
    try:
        rules = FilterRules.model_validate_json(rules_json)
    except Exception as e:
        raise HTTPException(400, f"Invalid rules JSON: {e}")
    out = []
    for f in files:
        try:
            data = json.loads(await f.read())
            preview_doc = quip_parser.preview_dict(data, rules)
            preview_doc["qc"] = qc_service.qc_preview_doc(preview_doc, rules).model_dump()
            out.append(preview_doc)
        except Exception as e:
            out.append({"doc_id": f.filename, "error": str(e)})
    return {"docs": out}

class QuipPullRequest(BaseModel):
    urls: list[str]
    sprint: str | None = None


def _extract_thread_id(url_or_id: str) -> str | None:
    value = str(url_or_id or "").strip()
    if not value:
        return None
    match = re.search(r"quip\.com/([A-Za-z0-9]+)", value)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9]+", value):
        return value
    return None

@router.post("/pull-quip")
async def pull_quip_docs(req: QuipPullRequest):
    """
    SSE streaming endpoint for pulling Quip documents with real-time progress.
    Returns Server-Sent Events stream.
    """
    from ..config import settings
    from ..services import chunker, vector_store
    import logging

    logger = logging.getLogger(__name__)

    async def generate_events():
        if not settings.quip_token:
            yield f"event: error\ndata: {json.dumps({'error': 'QUIP_TOKEN not configured'})}\n\n"
            return

        headers = {"Authorization": f"Bearer {settings.quip_token}"}
        rules = rules_store.load()
        total = len(req.urls)

        yield f"event: start\ndata: {json.dumps({'total': total})}\n\n"

        async with httpx.AsyncClient(base_url=settings.quip_base_url, timeout=30.0) as client:
            for idx, raw in enumerate(req.urls, 1):
                thread_id = _extract_thread_id(raw)
                if not thread_id:
                    yield f"event: error\ndata: {json.dumps({'index': idx, 'total': total, 'error': f'Invalid thread ID: {raw}'})}\n\n"
                    return

                try:
                    # Step 1: Fetching
                    yield f"event: progress\ndata: {json.dumps({'index': idx, 'total': total, 'step': 'fetching', 'thread_id': thread_id})}\n\n"
                    resp = await client.get(f"/threads/{thread_id}", headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                    thread = data.get("thread", {})
                    html = data.get("html", "")

                    doc = {
                        "thread_id": thread.get("id"),
                        "title": thread.get("title"),
                        "created_usec": thread.get("created_usec"),
                        "updated_usec": thread.get("updated_usec"),
                        "html": html
                    }

                    quip_dir = settings.quip_dir
                    quip_dir.mkdir(exist_ok=True, parents=True)
                    file_path = quip_dir / f"{thread_id}.json"
                    file_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

                    # Step 2: Auto-tagging
                    yield f"event: progress\ndata: {json.dumps({'index': idx, 'total': total, 'step': 'tagging', 'thread_id': thread_id, 'title': doc['title']})}\n\n"
                    await auto_tagger.auto_tag_doc(doc, rules)

                    # Step 3: Parsing
                    yield f"event: progress\ndata: {json.dumps({'index': idx, 'total': total, 'step': 'parsing', 'thread_id': thread_id})}\n\n"
                    parsed = quip_parser.parse_dict(doc, rules)

                    # Step 4: Ingesting
                    yield f"event: progress\ndata: {json.dumps({'index': idx, 'total': total, 'step': 'ingesting', 'thread_id': thread_id})}\n\n"
                    vector_store.delete_doc(parsed.doc_id)
                    chunks = chunker.chunk_doc(parsed)
                    category = parsed.prefix or "VSD"
                    vector_store.upsert_chunks(chunks, category=category)

                    if req.sprint:
                        vector_store.update_doc_metadata(parsed.doc_id, sprint=req.sprint)

                    # Step 5: Done
                    preview = quip_parser.preview_dict(doc, rules)
                    preview["qc"] = qc_service.qc_preview_doc(preview, rules).model_dump()

                    yield f"event: doc_complete\ndata: {json.dumps({'index': idx, 'total': total, 'doc': preview, 'chunks': len(chunks)})}\n\n"

                except Exception as e:
                    logger.exception("Failed to process %s", thread_id)
                    yield f"event: error\ndata: {json.dumps({'index': idx, 'total': total, 'thread_id': thread_id, 'error': str(e)})}\n\n"
                    return

        yield f"event: complete\ndata: {json.dumps({'total': total, 'rules': rules.model_dump()})}\n\n"

    return StreamingResponse(generate_events(), media_type="text/event-stream")
