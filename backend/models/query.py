from typing import Optional, Literal
from pydantic import BaseModel, Field

from .qc import QCReport


class QueryFilters(BaseModel):
    categories: Optional[list[str]] = None
    doc_ids: Optional[list[str]] = None
    sprints: Optional[list[str]] = None
    tags: Optional[list[str]] = None
    category_tags: Optional[list[str]] = None
    detail_tags: Optional[list[str]] = None


class QueryRequest(BaseModel):
    question: str
    history: list["QueryMessage"] = Field(default_factory=list)
    filters: QueryFilters = QueryFilters()
    top_k: int = 5
    mmr_lambda: Optional[float] = None
    qc_enabled: bool = True
    intent_override: Optional[Literal["rag", "aggregate"]] = None


class QueryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class Citation(BaseModel):
    chunk_id: str
    doc_id: str
    title: str
    category: str
    code: str
    sprint: str
    snippet: str
    score: float
    group_id: str = ""
    is_representative: bool = True
    sibling_count: int = 0
    keyword_score: float = 0.0
    metadata_score: float = 0.0
    matched_terms: list[str] = Field(default_factory=list)


class SimilarEvidenceGroup(BaseModel):
    group_id: str
    label: str
    count: int
    representative: Citation
    supporting: list[Citation] = Field(default_factory=list)


class QueryDebug(BaseModel):
    route: str = "rag"
    intent: str = "rag"
    candidate_count: int = 0
    group_count: int = 0
    selected_count: int = 0
    inferred_tags: list[str] = Field(default_factory=list)
    vector_candidate_count: int = 0
    keyword_candidate_count: int = 0
    mmr_used: bool = False


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    elapsed_ms: int
    evidence_groups: list[SimilarEvidenceGroup] = Field(default_factory=list)
    qc: Optional[QCReport] = None
    debug: QueryDebug = Field(default_factory=QueryDebug)


class CompareRequest(BaseModel):
    question: str
    sprint_a: str
    sprint_b: str
    top_k: int = 5
    qc_enabled: bool = True


class CompareResponse(BaseModel):
    sprint_a: str
    sprint_b: str
    result_a: QueryResponse
    result_b: QueryResponse
