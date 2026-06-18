import json
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from ..services import quip_parser, staging_store, chunker, vector_store
from ..models.ingest import ApprovalRequest, StagedDoc

router = APIRouter(prefix="/ingest", tags=["ingest"])


class ParseResponse(BaseModel):
    batch_id: str
    docs: list[dict]


@router.post("/parse", response_model=ParseResponse)
async def parse_files(files: list[UploadFile] = File(...)):
    parsed_docs = []
    for f in files:
        raw = json.loads(await f.read())
        parsed_docs.append(quip_parser.parse_dict(raw))

    batch_id = staging_store.create_batch(parsed_docs)
    return ParseResponse(
        batch_id=batch_id,
        docs=[
            {
                "doc_id": d.doc_id,
                "title": d.title,
                "code": d.code,
                "prefix": d.prefix,
                "word_count": d.word_count,
            }
            for d in parsed_docs
        ],
    )


@router.get("/batches/{batch_id}")
async def get_batch(batch_id: str):
    batch = staging_store.get_batch(batch_id)
    if batch is None:
        raise HTTPException(404, "Batch not found")
    return {"batch_id": batch_id, "docs": [_staged_to_dict(d) for d in batch.values()]}


@router.post("/approve")
async def approve(req: ApprovalRequest):
    """Ingest all PARSED docs in the batch (or the subset named by doc_ids)."""
    docs = staging_store.get_to_ingest(req.batch_id, req.doc_ids)
    if not docs:
        raise HTTPException(400, "No docs to ingest in batch")

    ingested, failed = 0, []
    for doc in docs:
        try:
            vector_store.delete_doc(doc.doc_id)   # purge old chunks first
            chunks = chunker.chunk_doc(doc.parsed)
            vector_store.upsert_chunks(chunks, category=doc.category)
            staging_store.mark_ingested(req.batch_id, doc.doc_id)
            ingested += 1
        except Exception as e:
            failed.append({"doc_id": doc.doc_id, "reason": str(e)})

    return {"ingested": ingested, "failed": failed}


def _staged_to_dict(d: StagedDoc) -> dict:
    return {
        "doc_id": d.doc_id,
        "batch_id": d.batch_id,
        "title": d.parsed.title,
        "code": d.parsed.code,
        "prefix": d.parsed.prefix,
        "category": d.category,
        "status": d.status,
        "word_count": d.parsed.word_count,
        "sprint": d.parsed.sprint,
    }
