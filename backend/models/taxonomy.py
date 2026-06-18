from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict

class TaxonomyCandidate(BaseModel):
    category: str
    subcategory: str
    tags: List[str]
    count: int = 0
    confidence: float = 1.0

class TaxonomyNode(BaseModel):
    category: str
    subcategory: str
    description: Optional[str] = ""
    examples: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    active: bool = True
    aliases: List[str] = Field(default_factory=list)

class TaxonomyTree(BaseModel):
    categories: List[TaxonomyNode]

class TaxonomyMergeRequest(BaseModel):
    from_category: str
    from_subcategory: str
    to_category: str
    to_subcategory: str

class TaxonomyRenameRequest(BaseModel):
    category: str
    subcategory: str
    new_category: str
    new_subcategory: str

class TaxonomyDeactivateRequest(BaseModel):
    category: str
    subcategory: str

class TaxonomyFeedbackRequest(BaseModel):
    row_id: str
    predicted_category: Optional[str] = None
    predicted_subcategory: Optional[str] = None
    predicted_tags: Optional[List[str]] = None
    final_category: str
    final_subcategory: str
    final_tags: List[str]
    action: Literal["approve", "edit", "reject"]
    rationale: Optional[str] = None
    reviewer: Optional[str] = None

class TaxonomyFeedbackApplySimilarRequest(BaseModel):
    row_id: str
    final_category: str
    final_subcategory: str
    final_tags: List[str]
    target_similarity_threshold: float = 0.85
    action: Literal["approve", "edit", "reject"] = "edit"
    reviewer: Optional[str] = None
    rationale: Optional[str] = None

class TaxonomyStore(BaseModel):
    version: int = 1
    mappings: Dict[str, str] = Field(default_factory=dict)
    nodes: List[TaxonomyNode] = Field(default_factory=list)
