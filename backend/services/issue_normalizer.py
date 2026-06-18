import re


FIELD_BOUNDARY_RE = re.compile(
    r"(?:\n|\s\|\s)(?:Response by|Response|Comment by|Comment|Status|Date):",
    re.IGNORECASE,
)
QUOTE_RE = re.compile(r"[\"“”‘’][^\"“”‘’]{0,160}[\"“”‘’]")
URL_RE = re.compile(r"https?://\S+")
LOCALE_RE = re.compile(r"\b(ZHCN|JAJP|ESMX|ESLA|PTBR|FRFR|DEDE|ENGB|FRCA)\b", re.IGNORECASE)


def extract_issue_text(text: str) -> str:
    marker = "Description/ Comment:"
    if marker in text:
        text = text.split(marker, 1)[1]
    match = FIELD_BOUNDARY_RE.search(text)
    if match:
        text = text[:match.start()]
    return text.strip()


def normalize_issue_text(text: str) -> str:
    text = extract_issue_text(text)
    text = URL_RE.sub(" ", text)
    text = QUOTE_RE.sub(" quoted ", text)
    text = LOCALE_RE.sub(" locale ", text)
    text = text.lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    tokens = [t for t in text.split() if len(t) > 1]
    return " ".join(tokens[:32])


def split_tags(meta: dict) -> list[str]:
    return [t.strip() for t in (meta.get("tags", "") or "").split(",") if t.strip()]


def memory_example(item: dict) -> dict:
    meta = item["metadata"]
    return {
        "chunk_id": item["chunk_id"],
        "doc_id": meta.get("doc_id", ""),
        "code": meta.get("code", ""),
        "title": meta.get("title", ""),
        "locale": meta.get("sheet", "") or "",
        "row_index": meta.get("row_index"),
        "tags": split_tags(meta),
        "text": item["text"][:500],
    }
