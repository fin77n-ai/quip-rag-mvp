import math
import re

from ..models.query import QueryFilters


TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from",
    "has", "have", "how", "i", "in", "is", "it", "me", "of", "on", "or", "that", "the",
    "there", "this", "to", "what", "when", "where", "which", "who", "why", "with", "you",
    "your", "about", "across", "all", "any", "find", "show", "tell", "please",
    "issue", "issues", "problem", "problems",
}
VOICEOVER_QUERY_MARKERS = ("配音", "旁白", "voiceover", "voice over", "vo")
VOICEOVER_TERMS = ("vo", "voiceover", "audio", "pronunciation")
RETAKE_QUERY_MARKERS = ("retake", "re-record", "rerecord", "重录", "返录", "重新录", "重配")
RETAKE_TERMS = ("retake", "re-record", "重录")


def matches_tag_filter(meta: dict, tag_filter: list[str] | None) -> bool:
    if not tag_filter:
        return True
    csv = meta.get("tags", "") or ""
    chunk_tags = {t.strip() for t in csv.split(",") if t.strip()}
    if "(untagged)" in tag_filter:
        return not chunk_tags
    return any(t in chunk_tags for t in tag_filter)


def semantic_score(raw_score: float, distance: float, rerank_used: bool) -> float:
    if rerank_used:
        return _clamp01(1 / (1 + math.exp(-raw_score)))
    return _clamp01(1 - distance)


def score_candidate(
    question: str,
    filters: QueryFilters,
    text: str,
    meta: dict,
    semantic: float,
) -> dict:
    keyword, keyword_terms = _keyword_score(question, text, meta)
    metadata, metadata_terms = _metadata_score(question, filters, meta)
    final = _clamp01((semantic * 0.50) + (keyword * 0.30) + (metadata * 0.20))
    matched_terms = []
    for term in keyword_terms + metadata_terms:
        if term not in matched_terms:
            matched_terms.append(term)
    return {
        "score": round(final, 4),
        "semantic_score": round(semantic, 4),
        "keyword_score": round(keyword, 4),
        "metadata_score": round(metadata, 4),
        "matched_terms": matched_terms[:12],
    }


def query_terms(question: str) -> list[str]:
    return _query_terms(question)


def keyword_match_score(question: str, text: str, meta: dict) -> tuple[float, list[str]]:
    return _keyword_score(question, text, meta)


def text_keyword_match_score(question: str, text: str) -> tuple[float, list[str]]:
    return _keyword_score(question, text, {})


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _query_terms(question: str) -> list[str]:
    terms = []
    for token in TOKEN_RE.findall(question.lower()):
        if token in STOPWORDS:
            continue
        if len(token) < 2 and not token.isdigit():
            continue
        if token not in terms:
            terms.append(token)
    q = question.lower()
    if any(marker in q for marker in VOICEOVER_QUERY_MARKERS):
        for term in VOICEOVER_TERMS:
            if term not in terms:
                terms.append(term)
    if "scratch" in q and "scratch" not in terms:
        terms.append("scratch")
    if any(marker in q for marker in RETAKE_QUERY_MARKERS):
        for term in RETAKE_TERMS:
            if term not in terms:
                terms.append(term)
    return terms


def _metadata_text(meta: dict) -> str:
    values = [
        meta.get("category", ""),
        meta.get("code", ""),
        meta.get("sprint", ""),
        meta.get("sheet", ""),
        meta.get("tags", ""),
        meta.get("is_issue", ""),
        meta.get("issue_summary", ""),
        meta.get("issue_type", ""),
        meta.get("owner", ""),
        meta.get("status", ""),
        meta.get("retake_explicit", ""),
        meta.get("retake_terms", ""),
        meta.get("title", ""),
        str(meta.get("row_index", "")),
    ]
    return " ".join(str(v) for v in values if v)


def _keyword_score(question: str, text: str, meta: dict) -> tuple[float, list[str]]:
    terms = _query_terms(question)
    if not terms:
        return 0.0, []
    haystack = f"{text} {_metadata_text(meta)}".lower() if meta else text.lower()
    matched = [term for term in terms if _contains_term(haystack, term)]
    return _clamp01(len(matched) / len(terms)), matched


def _contains_term(haystack: str, term: str) -> bool:
    if re.fullmatch(r"[a-z0-9]+", term):
        return re.search(rf"\b{re.escape(term)}\b", haystack) is not None
    return term in haystack


def _metadata_score(question: str, filters: QueryFilters, meta: dict) -> tuple[float, list[str]]:
    checks: list[tuple[bool, str]] = []
    if filters.categories:
        checks.append((meta.get("category") in filters.categories, "category"))
    if filters.sprints:
        checks.append(((meta.get("sprint") or "") in filters.sprints, "sprint"))
    if filters.doc_ids:
        checks.append((meta.get("doc_id") in filters.doc_ids, "doc"))
    if filters.tags:
        checks.append((matches_tag_filter(meta, filters.tags), "tag"))
    if filters.is_issue:
        checks.append(((meta.get("is_issue") or "") in filters.is_issue, "is_issue"))
    if filters.issue_types:
        checks.append(((meta.get("issue_type") or "") in filters.issue_types, "issue_type"))
    if filters.owners:
        checks.append(((meta.get("owner") or "") in filters.owners, "owner"))
    if filters.statuses:
        checks.append(((meta.get("status") or "") in filters.statuses, "status"))

    q = question.lower()
    for key, label in (
        ("code", "code"),
        ("sprint", "sprint"),
        ("category", "category"),
        ("sheet", "locale"),
        ("issue_type", "issue_type"),
        ("owner", "owner"),
        ("status", "status"),
    ):
        value = str(meta.get(key) or "").lower()
        if value and value in q:
            checks.append((True, label))
    for tag in (meta.get("tags", "") or "").split(","):
        tag_value = tag.strip()
        if tag_value and tag_value.lower() in q:
            checks.append((True, f"tag:{tag_value}"))

    if not checks:
        return 0.0, []
    matched = [label for ok, label in checks if ok]
    return _clamp01(len(matched) / len(checks)), matched
