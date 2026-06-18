from collections import Counter

from . import duck_lance_store, vector_store, llm_client
from .issue_normalizer import extract_issue_text, memory_example, normalize_issue_text, split_tags

UNTAGGED = "(untagged)"
ANALYSIS_MEMORY_LIMIT = 5000


def _top_counts(counter: Counter, limit: int = 100) -> list[dict]:
    return [
        {"key": key, "count": count}
        for key, count in sorted(counter.items(), key=lambda item: (-item[1], str(item[0])))[:limit]
    ]


def _issue_groups_from_memories(
    memories: list[dict],
    min_count: int = 1,
    limit: int = 50,
) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for item in memories:
        key = normalize_issue_text(item["text"])
        if not key:
            continue
        grouped.setdefault(key, []).append(item)

    groups = []
    for key, items in grouped.items():
        if len(items) < min_count:
            continue
        locales = sorted({item["metadata"].get("sheet", "(unknown)") or "(unknown)" for item in items})
        docs = {}
        tags = set()
        for item in items:
            meta = item["metadata"]
            docs[meta.get("doc_id", "")] = {
                "doc_id": meta.get("doc_id", ""),
                "code": meta.get("code", ""),
                "title": meta.get("title", ""),
            }
            item_tags = split_tags(meta)
            tags.update(item_tags if item_tags else [UNTAGGED])

        groups.append({
            "key": key,
            "summary": extract_issue_text(items[0]["text"])[:260],
            "count": len(items),
            "locales": locales,
            "docs": sorted(docs.values(), key=lambda doc: doc.get("code", "")),
            "tags": sorted(tags),
            "examples": [memory_example(item) for item in items[:5]],
        })

    groups.sort(key=lambda group: (-group["count"], -len(group["locales"]), -len(group["docs"]), group["summary"]))
    return groups[:limit]


def _summary_from_memories(memories: list[dict]) -> dict:
    by_tag: Counter = Counter()
    by_locale: Counter = Counter()
    by_doc: Counter = Counter()
    doc_titles: dict[str, str] = {}
    doc_codes: dict[str, str] = {}

    for item in memories:
        meta = item["metadata"]
        doc_id = meta.get("doc_id", "")
        doc_titles[doc_id] = meta.get("title", "")
        doc_codes[doc_id] = meta.get("code", "")
        by_doc[doc_id] += 1
        by_locale[meta.get("sheet", "(unknown)") or "(unknown)"] += 1
        tags = split_tags(meta)
        if tags:
            for tag in tags:
                by_tag[tag] += 1
        else:
            by_tag[UNTAGGED] += 1

    docs = []
    for doc_id, count in sorted(by_doc.items(), key=lambda item: (-item[1], doc_codes.get(item[0], ""))):
        docs.append({
            "doc_id": doc_id,
            "code": doc_codes.get(doc_id, ""),
            "title": doc_titles.get(doc_id, ""),
            "count": count,
        })

    return {
        "total_issues": len(memories),
        "total_docs": len(by_doc),
        "by_doc": docs,
        "by_locale": _top_counts(by_locale),
        "by_tag": _top_counts(by_tag),
    }


def repeated_issue_groups(
    category: str | None = None,
    sprint: str | None = None,
    tag: str | None = None,
    doc_id: str | None = None,
    min_count: int = 2,
    limit: int = 50,
) -> dict:
    list_func = duck_lance_store.list_memories if duck_lance_store.is_enabled() else vector_store.list_memories
    memories = list_func(category=category, sprint=sprint, tag=tag, doc_id=doc_id, limit=ANALYSIS_MEMORY_LIMIT)
    groups = _issue_groups_from_memories(memories, min_count=min_count, limit=limit)
    return {
        "total_groups": len(groups),
        "total_memories_scanned": len(memories),
        "filters": {
            "category": category or "",
            "sprint": sprint or "",
            "tag": tag or "",
            "doc_id": doc_id or "",
            "min_count": min_count,
        },
        "groups": groups[:limit],
    }


def analyze_video(doc_id: str, tag: str | None = None) -> dict:
    list_func = duck_lance_store.list_memories if duck_lance_store.is_enabled() else vector_store.list_memories
    memories = list_func(doc_id=doc_id, tag=tag, limit=ANALYSIS_MEMORY_LIMIT)
    groups = _issue_groups_from_memories(memories, min_count=1, limit=200)
    repeated = [group for group in groups if group["count"] >= 2]
    unique_by_locale: dict[str, list[dict]] = {}
    for group in groups:
        if len(group["locales"]) == 1:
            locale = group["locales"][0]
            unique_by_locale.setdefault(locale, []).append(group)

    doc = None
    if memories:
        meta = memories[0]["metadata"]
        doc = {
            "doc_id": meta.get("doc_id", ""),
            "code": meta.get("code", ""),
            "title": meta.get("title", ""),
            "category": meta.get("category", ""),
            "sprint": meta.get("sprint", "") or "",
        }

    return {
        "scope": "video",
        "doc": doc,
        "filters": {"doc_id": doc_id, "tag": tag or ""},
        "summary": _summary_from_memories(memories),
        "repeated_groups": repeated[:50],
        "unique_by_locale": {
            locale: groups[:20]
            for locale, groups in sorted(unique_by_locale.items(), key=lambda item: (-len(item[1]), item[0]))
        },
    }


def analyze_sprint(
    sprint: str,
    tag: str | None = None,
    category: str | None = None,
) -> dict:
    list_func = duck_lance_store.list_memories if duck_lance_store.is_enabled() else vector_store.list_memories
    memories = list_func(category=category, sprint=sprint, tag=tag, limit=ANALYSIS_MEMORY_LIMIT)
    repeated = _issue_groups_from_memories(memories, min_count=2, limit=100)
    recurring_across_docs = [group for group in repeated if len(group["docs"]) > 1]
    return {
        "scope": "sprint",
        "filters": {"sprint": sprint, "tag": tag or "", "category": category or ""},
        "summary": _summary_from_memories(memories),
        "repeated_groups": repeated[:50],
        "recurring_across_docs": recurring_across_docs[:50],
    }


def compare_sprints(
    sprint_a: str,
    sprint_b: str,
    tag: str | None = None,
    category: str | None = None,
) -> dict:
    list_func = duck_lance_store.list_memories if duck_lance_store.is_enabled() else vector_store.list_memories
    memories_a = list_func(category=category, sprint=sprint_a, tag=tag, limit=ANALYSIS_MEMORY_LIMIT)
    memories_b = list_func(category=category, sprint=sprint_b, tag=tag, limit=ANALYSIS_MEMORY_LIMIT)
    groups_a = _issue_groups_from_memories(memories_a, min_count=1, limit=1000)
    groups_b = _issue_groups_from_memories(memories_b, min_count=1, limit=1000)
    by_key_a = {group["key"]: group for group in groups_a}
    by_key_b = {group["key"]: group for group in groups_b}

    persistent = []
    for key in sorted(set(by_key_a) & set(by_key_b)):
        persistent.append({
            "key": key,
            "summary": by_key_a[key]["summary"],
            "count_a": by_key_a[key]["count"],
            "count_b": by_key_b[key]["count"],
            "locales_a": by_key_a[key]["locales"],
            "locales_b": by_key_b[key]["locales"],
            "docs_a": by_key_a[key]["docs"],
            "docs_b": by_key_b[key]["docs"],
            "examples_a": by_key_a[key]["examples"][:3],
            "examples_b": by_key_b[key]["examples"][:3],
        })
    persistent.sort(key=lambda group: (-(group["count_a"] + group["count_b"]), group["summary"]))

    resolved = sorted(
        (by_key_a[key] for key in set(by_key_a) - set(by_key_b)),
        key=lambda group: (-group["count"], group["summary"]),
    )
    new = sorted(
        (by_key_b[key] for key in set(by_key_b) - set(by_key_a)),
        key=lambda group: (-group["count"], group["summary"]),
    )

    return {
        "scope": "compare",
        "filters": {
            "sprint_a": sprint_a,
            "sprint_b": sprint_b,
            "tag": tag or "",
            "category": category or "",
        },
        "summary_a": _summary_from_memories(memories_a),
        "summary_b": _summary_from_memories(memories_b),
        "persistent": persistent[:50],
        "resolved": resolved[:50],
        "new": new[:50],
    }


async def analyze_story(
    scope: dict,
    max_groups: int = 20,
    examples_per_group: int = 3,
    max_evidence_chars: int = 500,
) -> dict:
    list_func = duck_lance_store.list_memories if duck_lance_store.is_enabled() else vector_store.list_memories
    memories = list_func(
        category=scope.get("category"),
        sprint=scope.get("sprint"),
        tag=scope.get("tag"),
        doc_id=scope.get("doc_id"),
        is_issue=scope.get("is_issue"),
        issue_type=scope.get("issue_type"),
        owner=scope.get("owner"),
        status=scope.get("status"),
        limit=10000,
    )

    summary = _summary_from_memories(memories)
    groups = _issue_groups_from_memories(memories, min_count=1, limit=max_groups)

    facts_lines = [
        f"Total Issues: {summary['total_issues']}",
        "Top Locales: " + ", ".join(f"{x['key']} ({x['count']})" for x in summary['by_locale'][:5]),
        "Top Tags: " + ", ".join(f"{x['key']} ({x['count']})" for x in summary['by_tag'][:5]),
        "Top Groups: " + ", ".join(f"{g['summary']} ({g['count']})" for g in groups[:5])
    ]
    facts_text = "\n".join(facts_lines)

    evidence_lines = []
    for g in groups:
        evidence_lines.append(f"\nGroup: {g['summary']} (Count: {g['count']})")
        for ex in g["examples"][:examples_per_group]:
            text = ex.get("text", "")[:max_evidence_chars].replace("\n", " ")
            evidence_lines.append(f"- {text}")

    evidence_text = "\n".join(evidence_lines)

    import os
    prompt_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "story_mode.txt")
    if os.path.exists(prompt_path):
        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt_tpl = f.read()
    else:
        prompt_tpl = "Based on these facts:\n{facts}\n\nAnd evidence:\n{evidence}\n\nWrite a narrative summary:"

    prompt = prompt_tpl.replace("{facts}", facts_text).replace("{evidence}", evidence_text)

    try:
        narrative = await llm_client.generate(prompt, model_type="smart")
    except Exception as e:
        narrative = f"LLM Generation Failed: {e}"

    return {
        "facts": summary,
        "evidence": groups,
        "narrative": narrative
    }
