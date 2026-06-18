from pydantic import BaseModel, Field


class RowTag(BaseModel):
    """Tags + flags for a single row inside a sheet/table."""
    tags: list[str] = Field(default_factory=list)
    excluded: bool = False
    is_noise: bool = False
    category_tag: str = ""
    detail_tags: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    rationale: str = ""
    review_required: bool = False
    review_reason: str = ""
    feedback_note: str = ""
    issue_source: str = ""
    is_issue: str = ""
    issue_summary: str = ""
    issue_type: str = ""
    owner: str = ""
    status: str = ""
    taxonomy_category: str = ""
    taxonomy_subcategory: str = ""
    taxonomy_tags: list[str] = Field(default_factory=list)
    taxonomy_confidence: float = 0.0
    taxonomy_rationale: str = ""


class DocTags(BaseModel):
    """All row-level tags for a single doc.
    Key format in `rows`: 'SheetName::row_index' (row_index is 1-based, header is 0)."""
    doc_id: str
    rows: dict[str, RowTag] = Field(default_factory=dict)
