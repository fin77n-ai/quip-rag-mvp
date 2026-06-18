"""Lightweight issue annotation helpers for Quip row-level metadata."""

from ..models.tags import RowTag


ISSUE_FIELD_NAMES = ("is_issue", "issue_summary", "issue_type", "owner", "status")

_ALIASES = {
    "is_issue": {
        "issue?",
        "is issue",
        "is_issue",
        "issue",
        "算问题",
        "是否问题",
    },
    "issue_summary": {
        "issue one-liner",
        "issue one liner",
        "issue summary",
        "issue_summary",
        "summary",
        "问题一句话",
        "问题描述",
    },
    "issue_type": {
        "issue type",
        "issue_type",
        "type",
        "problem type",
        "问题类型",
    },
    "owner": {
        "owner",
        "issue owner",
        "department",
        "责任方",
        "归因",
        "负责人",
    },
    "status": {
        "status",
        "issue status",
        "state",
        "状态",
    },
}

_YES_VALUES = {"yes", "y", "true", "1", "issue", "是", "算", "问题"}
_NO_VALUES = {"no", "n", "false", "0", "not issue", "not_issue", "否", "不算", "不是问题"}
_UNSURE_VALUES = {"unsure", "unknown", "maybe", "tbd", "?", "不确定", "未知"}

_STATUS_ALIASES = {
    "open": {"open", "active", "todo", "to do", "pending", "需要处理", "未解决"},
    "resolved": {"resolved", "fixed", "done", "closed", "complete", "completed", "已解决", "已修复"},
    "not_issue": {"not issue", "not_issue", "expected", "expected behavior", "no action", "不是问题", "不算问题"},
    "monitoring": {"monitoring", "watch", "follow up", "观察", "待观察"},
    "unknown": {"unknown", "unsure", "tbd", "?", "未知", "不确定"},
}


def normalize_header(value: str) -> str:
    return " ".join((value or "").strip().lower().replace("_", " ").split())


def field_for_header(header: str) -> str | None:
    normalized = normalize_header(header)
    for field, aliases in _ALIASES.items():
        if normalized in aliases:
            return field
    return None


def is_issue_column(header: str) -> bool:
    return field_for_header(header) is not None


def normalize_is_issue(value: str | bool | None) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    normalized = normalize_header(str(value or ""))
    if not normalized:
        return ""
    if normalized in _YES_VALUES:
        return "yes"
    if normalized in _NO_VALUES:
        return "no"
    if normalized in _UNSURE_VALUES:
        return "unsure"
    return normalized


def normalize_status(value: str | None) -> str:
    normalized = normalize_header(str(value or ""))
    if not normalized:
        return ""
    for status, aliases in _STATUS_ALIASES.items():
        if normalized in aliases:
            return status
    return normalized.replace(" ", "_")


def extract_issue_fields(cells: dict[str, str]) -> dict[str, str]:
    fields = {name: "" for name in ISSUE_FIELD_NAMES}
    for header, value in cells.items():
        field = field_for_header(header)
        if not field:
            continue
        text = str(value or "").strip()
        if field == "is_issue":
            text = normalize_is_issue(text)
        elif field == "status":
            text = normalize_status(text)
        fields[field] = text
    return {key: value for key, value in fields.items() if value}


def fields_from_row_tag(tag: RowTag | None) -> dict[str, str]:
    if not tag:
        return {}
    fields = {
        "is_issue": tag.is_issue,
        "issue_summary": tag.issue_summary,
        "issue_type": tag.issue_type,
        "owner": tag.owner,
        "status": tag.status,
    }
    normalized = {}
    for key, value in fields.items():
        text = str(value or "").strip()
        if not text:
            continue
        if key == "is_issue":
            text = normalize_is_issue(text)
        elif key == "status":
            text = normalize_status(text)
        normalized[key] = text
    return normalized


def merge_issue_fields(parsed_fields: dict | None, tag: RowTag | None) -> dict[str, str]:
    merged = {str(key): str(value) for key, value in (parsed_fields or {}).items() if value}
    merged.update(fields_from_row_tag(tag))
    return {key: merged.get(key, "") for key in ISSUE_FIELD_NAMES if merged.get(key)}


def has_issue_annotation(tag: RowTag) -> bool:
    return bool(fields_from_row_tag(tag))
