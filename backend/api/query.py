import uuid
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from ..models.query import QueryRequest, QueryResponse, CompareRequest, CompareResponse
from ..services import rag_engine

router = APIRouter(prefix="/query", tags=["query"])


@router.post("")
async def query(req: QueryRequest):
    trace_id = uuid.uuid4().hex
    return StreamingResponse(rag_engine.answer(req, trace_id), media_type="text/event-stream")


@router.post("/compare", response_model=CompareResponse)
async def compare(req: CompareRequest):
    trace_id = uuid.uuid4().hex
    return await rag_engine.compare(req, trace_id)
