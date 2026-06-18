from __future__ import annotations

import re

_EXPLICIT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("retake", re.compile(r"\bretake\b", re.IGNORECASE)),
    ("re-record", re.compile(r"\bre[\s-]?record(?:ed|ing)?\b", re.IGNORECASE)),
    ("redo-vo", re.compile(r"\bredo(?:\s+the)?\s+(?:vo|voice ?over|line|recording)\b", re.IGNORECASE)),
    ("record-again", re.compile(r"\brecord(?:ed)?\s+again\b", re.IGNORECASE)),
    ("new-recording", re.compile(r"\bnew\s+(?:vo|voice ?over|recording)\b", re.IGNORECASE)),
    ("重录", re.compile(r"重录|重新录|返录|重新配音|重配")),
]


def detect_explicit_retake(text: str) -> dict[str, str]:
    matched: list[str] = []
    for label, pattern in _EXPLICIT_PATTERNS:
        if pattern.search(text or ""):
            matched.append(label)
    unique = list(dict.fromkeys(matched))
    return {
        "retake_explicit": "yes" if unique else "no",
        "retake_terms": ",".join(unique),
    }
