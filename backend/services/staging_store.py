"""In-memory staging store for parsed-but-not-yet-ingested batches.
Simple for single-user local use — no persistence between restarts."""
import uuid
from ..models.ingest import StagedDoc, StageStatus
from ..models.quip import ParsedDoc


_batches: dict[str, dict[str, StagedDoc]] = {}


def create_batch(docs: list[ParsedDoc]) -> str:
    batch_id = str(uuid.uuid4())[:8]
    _batches[batch_id] = {
        doc.doc_id: StagedDoc(doc_id=doc.doc_id, batch_id=batch_id, parsed=doc)
        for doc in docs
    }
    return batch_id


def get_batch(batch_id: str) -> dict[str, StagedDoc] | None:
    return _batches.get(batch_id)


def get_doc(batch_id: str, doc_id: str) -> StagedDoc | None:
    batch = _batches.get(batch_id)
    return batch.get(doc_id) if batch else None


def get_to_ingest(batch_id: str, doc_ids: list[str] | None = None) -> list[StagedDoc]:
    """Return PARSED docs (optionally filtered by doc_ids) ready to ingest."""
    batch = _batches.get(batch_id, {})
    candidates = [d for d in batch.values() if d.status == StageStatus.PARSED]
    if doc_ids:
        candidates = [d for d in candidates if d.doc_id in doc_ids]
    return candidates


def mark_ingested(batch_id: str, doc_id: str) -> None:
    doc = get_doc(batch_id, doc_id)
    if doc:
        doc.status = StageStatus.INGESTED
