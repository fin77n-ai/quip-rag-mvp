import json
import logging
import re
from collections import Counter
from typing import Any

from ..models.qc import QCIssue, QCReport
from ..models.quip import ParsedDoc
from ..models.rules import FilterRules
from . import llm_client

logger = logging.getLogger(__name__)


def _status_from_issues(issues: list[QCIssue]) -> str:
    if any(issue.severity == "error" for issue in issues):
        return "fail"
    if any(issue.severity == "warning" for issue in issues):
        return "warning"
    return "pass"


def _summary(stage: str, issues: list[QCIssue]) -> str:
    if not issues:
        return f"{stage} QC passed"
    by_severity = Counter(issue.severity for issue in issues)
    parts = []
    if by_severity.get("error"):
        parts.append(f"{by_severity['error']} error")
    if by_severity.get("warning"):
        parts.append(f"{by_severity['warning']} warning")
    if by_severity.get("info"):
        parts.append(f"{by_severity['info']} info")
    return f"{stage} QC found " + ", ".join(parts)


def qc_preview_doc(preview: dict[str, Any], rules: FilterRules) -> QCReport:
    issues: list[QCIssue] = []
    if preview.get("error"):
        issues.append(QCIssue(
            severity="error",
            type="preview_error",
            message=str(preview["error"]),
            ref=str(preview.get("doc_id", "")),
        ))
        return QCReport(stage="preview", status="fail", summary="Preview failed", issues=issues)

    sheet_breakdown = preview.get("stats", {}).get("sheet_breakdown", []) or []
    kept_sheets = [sheet for sheet in sheet_breakdown if sheet.get("kept")]
    excluded_sheets = [sheet for sheet in sheet_breakdown if not sheet.get("kept")]
    rows_total = sum(int(sheet.get("rows_total") or 0) for sheet in kept_sheets)
    rows_kept = sum(int(sheet.get("rows_kept") or 0) for sheet in kept_sheets)
    table_rows = int(preview.get("table_rows_count") or 0)
    sections = int(preview.get("sections_count") or 0)
    total_chars = int(preview.get("total_chars") or 0)

    if not preview.get("doc_id"):
        issues.append(QCIssue(severity="error", type="missing_doc_id", message="Preview has no doc_id"))
    if not preview.get("title"):
        issues.append(QCIssue(severity="warning", type="missing_title", message="Preview has no title"))
    if not table_rows and not sections:
        issues.append(QCIssue(
            severity="error",
            type="empty_preview",
            message="Preview produced no table rows or sections",
            ref=str(preview.get("doc_id", "")),
        ))
    if kept_sheets and rows_total and rows_kept / rows_total < 0.2:
        issues.append(QCIssue(
            severity="warning",
            type="high_row_drop_ratio",
            message=f"Only {rows_kept}/{rows_total} rows were kept across included sheets",
            ref=str(preview.get("doc_id", "")),
        ))
    if not kept_sheets and excluded_sheets:
        issues.append(QCIssue(
            severity="error",
            type="all_sheets_excluded",
            message="All sheets were excluded by filter rules",
            ref=str(preview.get("doc_id", "")),
        ))
    if table_rows and rules.min_chunk_chars > 0 and total_chars < rules.min_chunk_chars:
        issues.append(QCIssue(
            severity="warning",
            type="short_preview_text",
            message="Preview text is shorter than the configured min_chunk_chars",
            ref=str(preview.get("doc_id", "")),
        ))
    if not rules.include_columns and not rules.exclude_columns:
        issues.append(QCIssue(
            severity="info",
            type="no_column_filters",
            message="No include or exclude column rules are configured",
        ))

    metrics = {
        "kept_sheets": len(kept_sheets),
        "excluded_sheets": len(excluded_sheets),
        "rows_total": rows_total,
        "rows_kept": rows_kept,
        "table_rows": table_rows,
        "sections": sections,
        "total_chars": total_chars,
    }
    status = _status_from_issues(issues)
    return QCReport(stage="preview", status=status, summary=_summary("Preview", issues), issues=issues, metrics=metrics)


def qc_chunks(parsed: ParsedDoc, chunks: list[dict]) -> QCReport:
    issues: list[QCIssue] = []
    row_chunks = [chunk for chunk in chunks if chunk.get("metadata", {}).get("row_key")]
    table_rows = len(parsed.table_rows or [])

    if not chunks:
        issues.append(QCIssue(
            severity="error",
            type="no_chunks",
            message="Parsed document produced zero chunks",
            ref=parsed.doc_id,
        ))
    if table_rows and not row_chunks:
        issues.append(QCIssue(
            severity="error",
            type="missing_row_chunks",
            message=f"Parsed document has {table_rows} table rows but no row chunks",
            ref=parsed.doc_id,
        ))
    if table_rows and row_chunks and len(row_chunks) / table_rows < 0.5:
        issues.append(QCIssue(
            severity="warning",
            type="row_chunk_drop_ratio",
            message=f"Only {len(row_chunks)}/{table_rows} table rows became row chunks",
            ref=parsed.doc_id,
        ))

    required = ("doc_id", "sheet", "row_index", "row_key")
    for chunk in row_chunks[:200]:
        meta = chunk.get("metadata", {})
        missing = [key for key in required if meta.get(key) in (None, "")]
        if missing:
            issues.append(QCIssue(
                severity="error",
                type="missing_row_metadata",
                message="Row chunk is missing metadata: " + ", ".join(missing),
                ref=str(chunk.get("id", "")),
            ))
            if len([issue for issue in issues if issue.type == "missing_row_metadata"]) >= 5:
                break

    empty_text = [chunk for chunk in chunks if not str(chunk.get("text") or "").strip()]
    if empty_text:
        issues.append(QCIssue(
            severity="error",
            type="empty_chunk_text",
            message=f"{len(empty_text)} chunks have empty text",
            ref=parsed.doc_id,
        ))

    metrics = {
        "table_rows": table_rows,
        "chunks": len(chunks),
        "row_chunks": len(row_chunks),
        "section_chunks": len(chunks) - len(row_chunks),
    }
    status = _status_from_issues(issues)
    return QCReport(stage="chunk", status=status, summary=_summary("Chunk", issues), issues=issues, metrics=metrics)


def qc_ingest_doc(parsed: ParsedDoc, chunks: list[dict]) -> QCReport:
    chunk_report = qc_chunks(parsed, chunks)
    issues = list(chunk_report.issues)
    if chunk_report.metrics.get("chunks", 0) <= 0:
        issues.append(QCIssue(
            severity="error",
            type="nothing_to_ingest",
            message="No chunks are available to write to the vector store",
            ref=parsed.doc_id,
        ))
    metrics = dict(chunk_report.metrics)
    metrics["doc_id"] = parsed.doc_id
    status = _status_from_issues(issues)
    return QCReport(stage="ingest", status=status, summary=_summary("Ingest", issues), issues=issues, metrics=metrics)


def qc_batch(reports: list[QCReport], stage: str = "batch") -> QCReport:
    issues: list[QCIssue] = []
    for report in reports:
        issues.extend(report.issues)
    metrics = {
        "reports": len(reports),
        "pass": sum(1 for report in reports if report.status == "pass"),
        "warning": sum(1 for report in reports if report.status == "warning"),
        "fail": sum(1 for report in reports if report.status == "fail"),
    }
    status = _status_from_issues(issues)
    return QCReport(stage=stage, status=status, summary=_summary(stage.title(), issues), issues=issues, metrics=metrics)


def _clean_json_response(text: str) -> str:
    start_idx = text.find('{')
    end_idx = text.rfind('}')
    if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
        return text[start_idx:end_idx + 1]
    return text.strip()


def _no_answer(answer: str) -> bool:
    lowered = answer.lower()
    return "couldn't find" in lowered or "could not find" in lowered or "找不到" in answer or "没有找到" in answer


_HIGH_RISK_RE = re.compile(
    r"\b(top|most|least|compare|comparison|trend|increase|decrease|count|counts|ranking|rank|summary|conclusion)\b",
    re.IGNORECASE,
)
_COUNT_CLAIM_RE = re.compile(r"\b\d+\b")


def _needs_compare_structure(question: str, route: str) -> bool:
    lowered = question.lower()
    return route == "compare" or "compare" in lowered or "vs" in lowered or "difference" in lowered


def _rule_qc_query_answer(question: str, answer: str, citations: list[Any], route: str = "rag") -> QCReport:
    issues: list[QCIssue] = []
    if not answer.strip():
        issues.append(QCIssue(severity="error", type="empty_answer", message="Answer is empty"))
    if not citations and not _no_answer(answer):
        issues.append(QCIssue(
            severity="warning",
            type="answer_without_citations",
            message="Answer has no citations but is not an explicit no-answer response",
        ))

    lowered_q = question.lower()
    lowered_a = answer.lower()
    if _HIGH_RISK_RE.search(question) and not citations and not _no_answer(answer):
        issues.append(QCIssue(
            severity="error",
            type="high_risk_without_evidence",
            message="High-risk analytical question answered without citation support",
        ))

    if _COUNT_CLAIM_RE.search(answer) and not citations and not _no_answer(answer):
        issues.append(QCIssue(
            severity="warning",
            type="count_claim_without_citations",
            message="Answer contains numeric claims without citations",
        ))

    if _needs_compare_structure(question, route):
        compare_markers = ("resolved", "persist", "new", "difference", "improved", "regressed", "新增", "持续", "解决", "差异")
        if not any(marker in lowered_a or marker in answer for marker in compare_markers):
            issues.append(QCIssue(
                severity="warning",
                type="weak_compare_structure",
                message="Compare answer may not clearly cover resolved, persistent, or new differences",
            ))

    if ("format" in lowered_q or "格式" in question) and "\n" not in answer.strip():
        issues.append(QCIssue(
            severity="warning",
            type="format_request_not_obvious",
            message="User requested formatting but answer appears to be a single block",
        ))

    high_risk = (
        route in {"stats", "compare", "analyze/repeated"}
        or bool(_HIGH_RISK_RE.search(question))
        or ("summary" in lowered_q or "总结" in question)
        or (len(citations) <= 1 and len(answer) > 240 and not _no_answer(answer))
    )

    if not citations:
        return QCReport(
            stage="query_answer",
            status=_status_from_issues(issues) if issues else "pass",
            summary=_summary("Query answer", issues) if issues else "Query answer QC passed for no-answer response",
            issues=issues,
            metrics={"citations": 0, "llm_qc_triggered": False, "high_risk": high_risk},
        )
    return QCReport(
        stage="query_answer",
        status=_status_from_issues(issues),
        summary=_summary("Query answer", issues),
        issues=issues,
        metrics={"citations": len(citations), "llm_qc_triggered": False, "high_risk": high_risk},
    )


def should_run_llm_qc(question: str, answer: str, citations: list[Any], route: str = "rag") -> bool:
    report = _rule_qc_query_answer(question, answer, citations, route)
    if report.status == "fail":
        return True
    if report.metrics.get("high_risk"):
        return True
    return False


async def qc_query_answer(question: str, answer: str, citations: list[Any], route: str = "rag", trace_id: str | None = None) -> QCReport:
    logger.info(f"[TraceID: {trace_id}] Running QC on answer for question: {question}")
    rule_report = _rule_qc_query_answer(question, answer, citations, route)
    if not citations:
        return rule_report
    if not should_run_llm_qc(question, answer, citations, route):
        return rule_report

    citation_payload = []
    for citation in citations[:12]:
        citation_payload.append({
            "chunk_id": getattr(citation, "chunk_id", ""),
            "code": getattr(citation, "code", ""),
            "title": getattr(citation, "title", ""),
            "snippet": getattr(citation, "snippet", "")[:700],
        })

    prompt = f"""You are a QC reviewer for a Quip RAG answer.
Check whether the answer actually addresses the user question, follows the expected structure, and stays grounded in the provided citations.

<rules>
- ALWAYS mark fail if the answer does not answer the user question, invents counts/examples/labels/conclusions not supported by citations, or seriously mishandles compare/summary structure.
- ALWAYS mark warning if the answer is mostly grounded but misses an obvious citation, is too vague, or the structure is weak.
- ALWAYS mark pass if the answer is well supported.
- NEVER require every sentence to be cited, but CRITICAL: important claims MUST be supported.
- ALWAYS prefer concise repair instructions like "Answer the ranking question directly and remove unsupported count claims."
</rules>

<route>
{route}
</route>

<question>
{question}
</question>

<answer>
{answer}
</answer>

<citations>
{json.dumps(citation_payload, ensure_ascii=False, indent=2)}
</citations>

Return your <reasoning> FIRST, then ONLY JSON with this schema:
{{
  "status": "pass" | "warning" | "fail",
  "summary": "short summary",
  "issues": [
    {{"severity": "warning" | "error" | "info", "type": "short_type", "message": "specific issue", "ref": "chunk_id or code"}}
  ],
  "repair_instruction": "one short instruction for revising the answer, or empty string if not needed"
}}
"""
    result = await llm_client.generate_with_metrics(prompt, model_type="fast")
    try:
        parsed = json.loads(_clean_json_response(result.text))
        report = QCReport.model_validate({
            "stage": "query_answer",
            "status": parsed.get("status", "warning"),
            "summary": parsed.get("summary", ""),
            "issues": parsed.get("issues", []),
            "metrics": {
                "citations": len(citations),
                "llm_qc_triggered": True,
                "high_risk": rule_report.metrics.get("high_risk", False),
                "repair_instruction": parsed.get("repair_instruction", ""),
                "prompt_tokens": result.prompt_tokens,
                "candidates_tokens": result.candidates_tokens,
                "total_tokens": result.total_tokens,
            },
        })
        if rule_report.issues:
            merged = list(rule_report.issues) + [
                issue for issue in report.issues
                if (issue.type, issue.message, issue.ref) not in {(x.type, x.message, x.ref) for x in rule_report.issues}
            ]
            report = report.model_copy(update={
                "status": _status_from_issues(merged) if report.status != "pass" or rule_report.status != "pass" else "pass",
                "issues": merged,
            })
        return report
    except Exception as exc:
        return QCReport(
            stage="query_answer",
            status="warning",
            summary="Query answer QC could not parse LLM response",
            issues=rule_report.issues + [QCIssue(
                severity="warning",
                type="qc_parse_error",
                message=str(exc),
            )],
            metrics={
                "citations": len(citations),
                "llm_qc_triggered": True,
                "high_risk": rule_report.metrics.get("high_risk", False),
                "prompt_tokens": result.prompt_tokens,
                "candidates_tokens": result.candidates_tokens,
                "total_tokens": result.total_tokens,
            },
        )
