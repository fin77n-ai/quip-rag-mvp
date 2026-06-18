from enum import Enum
from typing import Optional
from pydantic import BaseModel
from .quip import ParsedDoc


class StageStatus(str, Enum):
    PARSED = "PARSED"
    INGESTED = "INGESTED"


class StagedDoc(BaseModel):
    doc_id: str
    batch_id: str
    parsed: ParsedDoc
    status: StageStatus = StageStatus.PARSED

    @property
    def category(self) -> str:
        return self.parsed.prefix or "OTHER"


class ApprovalRequest(BaseModel):
    batch_id: str
    doc_ids: Optional[list[str]] = None   # None = ingest ALL parsed docs in batch
