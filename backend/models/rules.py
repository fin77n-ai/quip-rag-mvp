from pydantic import BaseModel


class FilterRules(BaseModel):
    """Global noise-filter rules applied at parse time."""
    exclude_sheets: list[str] = []           # table titles (case-insensitive exact)
    exclude_columns: list[str] = []          # column headers to drop
    include_columns: list[str] = []          # if non-empty, ONLY these columns kept (whitelist)
    exclude_row_patterns: list[str] = []
    exclude_section_headings: list[str] = []
    placeholder_chars: list[str] = ["☐", "☑", "​", "n/a", "N/A", "​", "—", "-"]
    drop_empty_rows: bool = True
    min_chunk_chars: int = 10


DEFAULT_RULES = FilterRules(
    exclude_sheets=["GLOBAL", "Check Box", "Overall Guidance"],
    exclude_columns=["Date", "Timestamp", "Date (2)", "Date (3)", "Date (4)"],
    include_columns=["Description/ Comment", "Response", "Response by"],
    drop_empty_rows=True,
    min_chunk_chars=10,
)
