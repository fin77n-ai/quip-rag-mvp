from typing import Any, Literal

from pydantic import BaseModel, Field


QCStatus = Literal["pass", "warning", "fail"]
QCSeverity = Literal["info", "warning", "error"]


class QCIssue(BaseModel):
    severity: QCSeverity = "warning"
    type: str
    message: str
    ref: str = ""


class QCReport(BaseModel):
    stage: str
    status: QCStatus = "pass"
    summary: str = ""
    issues: list[QCIssue] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
