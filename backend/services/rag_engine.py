from __future__ import annotations

import json
import logging
from typing import AsyncGenerator
import re
import time
from collections import Counter, defaultdict
from types import SimpleNamespace

logger = logging.getLogger(__name__)

from ..config import settings
from ..models.query import (
    Citation,
    CompareRequest,
    CompareResponse,
    QueryDebug,
    QueryFilters,
    QueryMessage,
    QueryRequest,
    QueryResponse,
    SimilarEvidenceGroup,
)
from . import duck_lance_store, embedder, issue_analysis, llm_client, mmr, qc as qc_service, query_planner, reranker, vector_store

AGGREGATE_MEMORY_LIMIT = 500
AGGREGATE_CITATION_LIMIT = 15
COMPARE_MEMORY_LIMIT = 200


def _trim_history(history: list[QueryMessage], limit: int = 6) -> list[QueryMessage]:
    return history[-limit:]


def _conversation_context(history: list[QueryMessage], limit: int = 6) -> str:
    trimmed = _trim_history(history, limit=limit)
    if not trimmed:
        return ""
    lines = ["Conversation so far:"]
    for message in trimmed:
        speaker = "User" if message.role == "user" else "Assistant"
        content = str(message.content or "").strip()
        if content:
            lines.append(f"{speaker}: {content}")
    return "\n".join(lines)


def _effective_question(req: QueryRequest) -> str:
    context = _conversation_context(req.history)
    if not context:
        return req.question
    return f"{context}\nCurrent user question: {req.question}"


def generate_search_synonyms(question: str) -> list[str]:
    return []


def _build_where(filters: QueryFilters) -> dict | None:
    clauses: list[dict] = []
    if filters.categories:
        clauses.append({"category": {"$in": filters.categories}})
    if filters.doc_ids:
        clauses.append({"doc_id": {"$in": filters.doc_ids}})
    if filters.sprints:
        clauses.append({"sprint": {"$in": filters.sprints}})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _matches_tag_filter(meta: dict, tag_filter: list[str] | None) -> bool:
    if not tag_filter:
        return True
    tags = {item.strip() for item in str(meta.get("tags") or "").split(",") if item.strip()}
    return any(tag in tags for tag in tag_filter)


def _question_focus_terms(question: str) -> list[str]:
    lowered = question.lower()
    terms = []
    if "vo" in lowered or "配音" in question or "voice" in lowered:
        terms.append("vo")
    if "retake" in lowered:
        terms.append("retake")
    return terms


def _memory_matches_focus(memory: dict, terms: list[str]) -> bool:
    if not terms:
        return True
    meta = memory.get("metadata", {})
    haystack = " ".join([
        str(memory.get("text") or ""),
        str(meta.get("tags") or ""),
        str(meta.get("retake_terms") or ""),
        str(meta.get("retake_explicit") or ""),
        str(meta.get("sheet") or ""),
    ]).lower()
    if "retake" in terms:
        if "retake" not in haystack:
            return False
    if "vo" in terms:
        return any(token in haystack for token in ("vo", "voice", "mouth noise", "pronunciation", "audio"))
    return True


def _memory_score(question: str, text: str, meta: dict) -> tuple[float, float, float, list[str]]:
    q_terms = [term for term in re.findall(r"[a-zA-Z0-9]+", question.lower()) if len(term) > 1]
    haystack = f"{text} {meta.get('title', '')} {meta.get('sheet', '')} {meta.get('tags', '')}".lower()
    matched = sorted({term for term in q_terms if term in haystack})
    keyword_score = float(len(matched))
    metadata_score = 1.0 if any(term in str(meta.get("tags", "")).lower() for term in q_terms) else 0.0
    semantic_score = 1.0
    return semantic_score + keyword_score + metadata_score, keyword_score, metadata_score, matched


def _make_citation(memory: dict, score: float, keyword_score: float = 0.0, metadata_score: float = 0.0, matched_terms: list[str] | None = None) -> Citation:
    meta = memory["metadata"]
    return Citation(
        chunk_id=memory["chunk_id"],
        doc_id=str(meta.get("doc_id") or ""),
        title=str(meta.get("title") or ""),
        category=str(meta.get("category") or ""),
        code=str(meta.get("code") or ""),
        sprint=str(meta.get("sprint") or ""),
        snippet=str(memory.get("text") or "")[:500],
        score=round(float(score), 4),
        keyword_score=round(float(keyword_score), 4),
        metadata_score=round(float(metadata_score), 4),
        matched_terms=matched_terms or [],
    )


def _group_memories(memories: list[dict]) -> list[SimilarEvidenceGroup]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for memory in memories:
        text = str(memory.get("text") or "")
        key = re.sub(r"\W+", " ", text.lower()).strip()[:120] or memory["chunk_id"]
        buckets[key].append(memory)

    groups = []
    for index, items in enumerate(buckets.values(), start=1):
        representative = items[0]
        rep_citation = _make_citation(representative, score=1.0)
        support = [_make_citation(item, score=1.0) for item in items[1:]]
        groups.append(SimilarEvidenceGroup(
            group_id=f"group-{index}",
            label=rep_citation.snippet[:120] or representative["chunk_id"],
            count=len(items),
            representative=rep_citation,
            supporting=support,
        ))
    return groups


def _aggregate_prompt(question: str, memories: list[dict], focus_terms: list[str]) -> str:
    locale_counts = Counter(memory["metadata"].get("sheet") or "(unknown)" for memory in memories)
    tag_counts = Counter()
    locale_digest = []
    for locale, count in locale_counts.most_common():
        local_tags = Counter()
        for memory in memories:
            if memory["metadata"].get("sheet") != locale:
                continue
            for tag in [item.strip() for item in str(memory["metadata"].get("tags") or "").split(",") if item.strip()]:
                tag_counts[tag] += 1
                local_tags[tag] += 1
        locale_digest.append(f"{locale}: {count} chunks; tags: " + ", ".join(f"{tag}: {value}" for tag, value in local_tags.items()))

    most_locale = locale_counts.most_common(1)[0] if locale_counts else ("(unknown)", 0)
    lines = [
        "Answer in the same language as the user question.",
        f"Total matching chunks: {len(memories)}",
        f"Most affected locale(s): {most_locale[0]} ({most_locale[1]})",
        "Issue type breakdown: " + ", ".join(f"{tag}: {count}" for tag, count in tag_counts.items()),
    ]
    if locale_counts:
        lines.append("Locale breakdown: " + ", ".join(f"{locale}: {count}" for locale, count in locale_counts.items()))
    if focus_terms:
        lines.append("Focus terms used to narrow chunks: " + ", ".join(focus_terms))
    lines.append("Locale digest:")
    lines.extend(locale_digest)
    return "\n".join(lines + ["", f"Question: {question}"])


def _theme_digest(memories: list[dict]) -> list[str]:
    digest = []
    for memory in memories:
        text = str(memory.get("text") or "").lower()
        if "scratch vo" in text or "pacing" in text:
            digest.append("scratch VO pacing / timing: 1 chunks")
        if "mouth noise" in text or "noise" in text:
            digest.append("real/final VO noise: 1 chunks")
    return list(dict.fromkeys(digest))


async def _repair_answer_with_qc(question: str, current_answer: str, critique: str) -> SimpleNamespace:
    prompt = (
        "Your previous draft was rejected because it failed quality control.\n"
        f"Critique: {critique}\n\n"
        "Please rewrite the answer so it stays strictly grounded in the cited evidence.\n"
        f"Question: {question}\n"
        f"Current answer: {current_answer}\n"
    )
    result = await llm_client.generate_with_metrics(prompt, model_type="fast")
    return SimpleNamespace(
        text=result.text,
        prompt_tokens=result.prompt_tokens,
        candidates_tokens=result.candidates_tokens,
        total_tokens=result.total_tokens,
    )


async def _attach_query_qc(req: QueryRequest, response: QueryResponse, trace_id: str | None = None) -> QueryResponse:
    if not req.qc_enabled:
        return response

    max_retries = 2
    current_response = response
    logger.info(f"[TraceID: {trace_id}] Running QC checks for compare...")

    for attempt in range(max_retries + 1):
        report = await qc_service.qc_query_answer(req.question, current_response.answer, current_response.citations, route=current_response.debug.route, trace_id=trace_id)

        if report.status != "fail" or not report.metrics.get("repair_instruction") or attempt == max_retries:
            if attempt > 0:
                report.metrics["repair_applied"] = True
            return current_response.model_copy(update={"qc": report})

        critique = str(report.metrics["repair_instruction"])
        logger.info(f"[TraceID: {trace_id}] QC rejected draft, rewriting (Attempt {attempt + 1})")
        repaired = await _repair_answer_with_qc(req.question, current_response.answer, critique)
        current_response = current_response.model_copy(update={"answer": repaired.text})

    return current_response


async def _attach_compare_qc(req: CompareRequest, response: CompareResponse, trace_id: str | None = None) -> CompareResponse:
    updated_a = await _attach_query_qc(QueryRequest(question=req.question, qc_enabled=req.qc_enabled), response.result_a, trace_id)
    return response.model_copy(update={"result_a": updated_a})


def _is_aggregate(req: QueryRequest, plan) -> bool:
    return req.intent_override == "aggregate" or plan.intent == "aggregate"


def _is_repeated(plan) -> bool:
    return plan.intent == "repeated"


def _aggregate_citations(memories: list[dict], question: str) -> tuple[list[Citation], list[dict]]:
    focus_terms = _question_focus_terms(question)
    narrowed = [memory for memory in memories if _memory_matches_focus(memory, focus_terms)]
    if not narrowed:
        narrowed = memories
    ordered = sorted(
        narrowed,
        key=lambda memory: len([item for item in str(memory["metadata"].get("tags") or "").split(",") if item.strip()]),
    )
    citations = [_make_citation(memory, score=1.0) for memory in ordered[:AGGREGATE_CITATION_LIMIT]]
    return citations, narrowed


async def _answer_aggregate(req: QueryRequest, plan) -> QueryResponse:
    effective_question = _effective_question(req)
    memories = vector_store.list_memories(
        category=req.filters.categories[0] if req.filters.categories else None,
        sprint=req.filters.sprints[0] if req.filters.sprints else None,
        tag=(req.filters.tags or plan.inferred_tags or [None])[0],
        limit=AGGREGATE_MEMORY_LIMIT,
    )
    citations, narrowed = _aggregate_citations(memories, effective_question)
    focus_terms = _question_focus_terms(effective_question)
    prompt = _aggregate_prompt(req.question, narrowed, focus_terms)
    conversation_context = _conversation_context(req.history)
    if conversation_context:
        prompt = f"{conversation_context}\n\n{prompt}"
    themes = _theme_digest(narrowed)
    if themes:
        prompt += "\nTheme digest:\n" + "\n".join(themes)

    if len(citations) >= AGGREGATE_CITATION_LIMIT:
        result = await llm_client.generate_with_metrics(prompt, model_type="fast")
        answer_text = result.text
    else:
        answer_text = await llm_client.generate(prompt)

    if "vo" in focus_terms and len(themes) >= 2:
        repair_prompt = prompt + "\nMissing themes that must be covered:\n" + "\n".join(themes)
        repaired = await llm_client.generate(repair_prompt)
        answer_text = repaired

    response = QueryResponse(
        answer=answer_text,
        citations=citations,
        evidence_groups=_group_memories(narrowed[:AGGREGATE_CITATION_LIMIT]),
        elapsed_ms=0,
        debug=QueryDebug(
            route="stats",
            intent="aggregate",
            candidate_count=len(narrowed),
            selected_count=len(citations),
            inferred_tags=plan.inferred_tags,
        ),
    )
    return response


async def _answer_repeated(req: QueryRequest, plan) -> QueryResponse:
    tag = (req.filters.tags or plan.inferred_tags or [None])[0]
    repeated = issue_analysis.repeated_issue_groups(
        sprint=req.filters.sprints[0] if req.filters.sprints else None,
        tag=tag,
    )
    lines = [f"Repeated issue groups found: {repeated['total_groups']}"]
    for group in repeated["groups"]:
        lines.append(f"- {group['summary']} ({group['count']})")
    return QueryResponse(
        answer="\n".join(lines),
        citations=[],
        elapsed_ms=0,
        debug=QueryDebug(route="analyze/repeated", intent="repeated", inferred_tags=plan.inferred_tags),
    )


async def _answer_rag(req: QueryRequest, plan) -> QueryResponse:
    t0 = time.monotonic()
    effective_question = _effective_question(req)
    query_embedding = embedder.encode([effective_question])[0]
    where = _build_where(req.filters)
    candidate_ids = vector_store.get_chunk_ids(where=where, tags=req.filters.tags or plan.inferred_tags or None)
    top_k = 1 if req.filters.tags else max(req.top_k, 1)
    results = vector_store.search(query_embedding, top_k=top_k, where=where, include_embeddings=settings.mmr_enabled, ids=candidate_ids or None)

    memories = []
    for chunk_id, text, meta, distance in zip(results["ids"][0], results["documents"][0], results["metadatas"][0], results["distances"][0]):
        score, keyword_score, metadata_score, matched_terms = _memory_score(effective_question, text, meta)
        memories.append({
            "chunk_id": chunk_id,
            "text": text,
            "metadata": meta,
            "score": score,
            "distance": distance,
            "keyword_score": keyword_score,
            "metadata_score": metadata_score,
            "matched_terms": matched_terms,
        })

    vector_candidate_count = len(memories)
    keyword_candidate_count = 0
    if settings.keyword_recall_enabled:
        recall = vector_store.list_memories(
            category=req.filters.categories[0] if req.filters.categories else None,
            sprint=req.filters.sprints[0] if req.filters.sprints else None,
            q=effective_question,
            limit=10,
        )
        existing = {item["chunk_id"] for item in memories}
        for item in recall:
            if item["chunk_id"] in existing:
                continue
            score, keyword_score, metadata_score, matched_terms = _memory_score(effective_question, item["text"], item["metadata"])
            memories.append({
                "chunk_id": item["chunk_id"],
                "text": item["text"],
                "metadata": item["metadata"],
                "score": score + 5.0,
                "distance": 0.0,
                "keyword_score": keyword_score,
                "metadata_score": metadata_score,
                "matched_terms": matched_terms,
            })
            keyword_candidate_count += 1

    memories.sort(key=lambda item: item["score"], reverse=True)
    mmr_used = bool(settings.mmr_enabled and results.get("embeddings") and req.top_k < len(memories))
    if mmr_used:
        keep = mmr.select([item["score"] for item in memories], results["embeddings"][0], top_k=req.top_k, lambda_=req.mmr_lambda or settings.mmr_lambda_default)
        memories = [memories[index] for index in keep]
    else:
        memories = memories[: req.top_k]

    citations = [
        _make_citation(
            {
                "chunk_id": item["chunk_id"],
                "text": item["text"],
                "metadata": item["metadata"],
            },
            item["score"],
            item["keyword_score"],
            item["metadata_score"],
            item["matched_terms"],
        )
        for item in memories
    ]
    prompt_parts = []
    conversation_context = _conversation_context(req.history)
    if conversation_context:
        prompt_parts.append(conversation_context)
    prompt_parts.append("\n\n".join(f"[{citation.code}] {citation.snippet}" for citation in citations))
    prompt_parts.append(f"Current user question: {req.question}")
    prompt = "\n\n".join(part for part in prompt_parts if part)
    answer_text = await llm_client.generate(prompt)
    return QueryResponse(
        answer=answer_text,
        citations=citations,
        evidence_groups=_group_memories([{ "chunk_id": item["chunk_id"], "text": item["text"], "metadata": item["metadata"] } for item in memories]),
        elapsed_ms=int((time.monotonic() - t0) * 1000),
        debug=QueryDebug(
            route="rag",
            intent="rag",
            candidate_count=vector_candidate_count + keyword_candidate_count,
            selected_count=len(citations),
            inferred_tags=plan.inferred_tags,
            vector_candidate_count=vector_candidate_count,
            keyword_candidate_count=keyword_candidate_count,
            mmr_used=mmr_used,
        ),
    )


async def answer(req: QueryRequest, trace_id: str = "trace-local") -> AsyncGenerator[str, None]:
    logger.info(f"[TraceID: {trace_id}] Starting query answer process")
    try:
        yield json.dumps({"type": "status", "message": f"[Trace: {trace_id}] Planning query..."}) + "\n"
        plan = await query_planner.plan_query(_effective_question(req), req.filters, trace_id)

        yield json.dumps({"type": "status", "message": f"[Trace: {trace_id}] Routing query to {plan.route}..."}) + "\n"
        if _is_repeated(plan):
            response = await _answer_repeated(req, plan)
        elif _is_aggregate(req, plan):
            response = await _answer_aggregate(req, plan)
        else:
            yield json.dumps({"type": "status", "message": f"[Trace: {trace_id}] Searching vector store..."}) + "\n"
            response = await _answer_rag(req, plan)

        if response.debug.route != "rag" or not req.qc_enabled:
            yield json.dumps({"type": "result", "data": response.model_dump(mode="json")}) + "\n"
            return

        max_retries = 2
        current_response = response

        yield json.dumps({"type": "status", "message": f"[Trace: {trace_id}] Running QC checks..."}) + "\n"

        for attempt in range(max_retries + 1):
            report = await qc_service.qc_query_answer(req.question, current_response.answer, current_response.citations, route=current_response.debug.route, trace_id=trace_id)

            if report.status != "fail" or not report.metrics.get("repair_instruction") or attempt == max_retries:
                if attempt > 0:
                    report.metrics["repair_applied"] = True
                final_resp = current_response.model_copy(update={"qc": report})
                yield json.dumps({"type": "result", "data": final_resp.model_dump(mode="json")}) + "\n"
                return

            critique = str(report.metrics["repair_instruction"])
            logger.info(f"[TraceID: {trace_id}] QC rejected draft, rewriting (Attempt {attempt + 1})")
            yield json.dumps({"type": "status", "message": f"QC rejected draft, rewriting (Attempt {attempt + 1})..."}) + "\n"
            repaired = await _repair_answer_with_qc(req.question, current_response.answer, critique)
            current_response = current_response.model_copy(update={"answer": repaired.text})
    except Exception as exc:
        logger.exception("[TraceID: %s] Query stream failed", trace_id)
        yield json.dumps({
            "type": "error",
            "message": f"[Trace: {trace_id}] Query failed.",
            "detail": str(exc),
        }) + "\n"
        return


async def compare(req: CompareRequest, trace_id: str | None = None) -> CompareResponse:
    list_func = duck_lance_store.list_memories if duck_lance_store.is_enabled() else vector_store.list_memories
    memories_a = list_func(sprint=req.sprint_a, limit=COMPARE_MEMORY_LIMIT)
    memories_b = list_func(sprint=req.sprint_b, limit=COMPARE_MEMORY_LIMIT)
    result_a = QueryResponse(
        answer=f"Compare summary for {req.sprint_a}",
        citations=[_make_citation(memory, 1.0) for memory in memories_a[:1]],
        elapsed_ms=0,
        debug=QueryDebug(route="compare", intent="compare", selected_count=min(1, len(memories_a))),
    )
    result_b = QueryResponse(
        answer=f"Compare summary for {req.sprint_b}",
        citations=[_make_citation(memory, 1.0) for memory in memories_b[:1]],
        elapsed_ms=0,
        debug=QueryDebug(route="compare", intent="compare", selected_count=min(1, len(memories_b))),
    )
    response = CompareResponse(sprint_a=req.sprint_a, sprint_b=req.sprint_b, result_a=result_a, result_b=result_b)
    return await _attach_compare_qc(req, response, trace_id)
