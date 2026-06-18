from datetime import datetime
from typing import Optional
from pydantic import BaseModel, field_validator


class RawQuipDoc(BaseModel):
    source: str = "quip"
    thread_id: str
    title: str
    created_usec: int
    updated_usec: int
    html: str
    comments: list[dict] = []
    raw: dict = {}  # original dict preserved


class ParsedDoc(BaseModel):
    doc_id: str           # = thread_id
    title: str
    prefix: str           # category: "MS", "VSD", etc.
    code: str             # full doc code: "MS0005", "VSD0004", etc.
    plain_text: str       # HTML stripped
    sections: list[str]   # split by heading for smarter chunking
    word_count: int
    created_at: datetime
    updated_at: datetime
    comment_count: int = 0
    sprint: Optional[str] = None    # hierarchical path like "Sprint-2025-Q1/Phase-A"
    table_rows: list[dict] = []     # NEW: structured rows for per-row chunking
    # each dict: {sheet: str, row_index: int, cells: {col_header: value, ...}}
