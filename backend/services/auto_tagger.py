import asyncio
import json
import logging
import re

from ..config import settings
from ..models.rules import FilterRules
from ..models.tags import DocTags, RowTag
from . import feedback_retriever, llm_client, quip_parser, retake_detector, rules_store, tags_store

logger = logging.getLogger(__name__)

AUTO_TAG_BATCH_SIZE = 15
AUTO_TAG_LEAF_ATTEMPTS = 2
REVIEW_THRESHOLD = 0.8
ALLOWED_CATEGORY_TAGS = ["Translation", "Voice Over", "Animation", "Source"]
SUMMARY_DETAIL_TAGS = {
    "Translation": ("validation", "terminology", "locale difference", "ui text", "instructions"),
    "Voice Over": ("validation", "script mismatch", "audio quality", "pronunciation", "pacing", "retake"),
    "Animation": ("validation", "post editing", "ui capture", "motion timing", "layout"),
    "Source": ("validation", "source mismatch", "guidance", "locale difference", "source asset"),
}
_LOW_SIGNAL_CONFIRMATION_PATTERNS = [
    re.compile(r"\breviewed and no comments?\b", re.IGNORECASE),
    re.compile(r"\breviewed and no issues?\b", re.IGNORECASE),
    re.compile(r"\bno comments?\b", re.IGNORECASE),
    re.compile(r"\bno issues? found\b", re.IGNORECASE),
    re.compile(r"\bno issues?\b", re.IGNORECASE),
]
_WORKFLOW_STATUS_PATTERNS = [
    re.compile(r"\breviewed and comments? added\b", re.IGNORECASE),
    re.compile(r"\bcomments? added\b", re.IGNORECASE),
    re.compile(r"\bcleaned-?up updated\b", re.IGNORECASE),
    re.compile(r"\breviewed and commented file uploaded\b", re.IGNORECASE),
    re.compile(r"\bfile uploaded\b", re.IGNORECASE),
    re.compile(r"\bupdated to v\d+\b", re.IGNORECASE),
    re.compile(r"\buploaded on box\b", re.IGNORECASE),
]
_SPECIFIC_ISSUE_PATTERNS = [
    re.compile(r"\bneeds? to be updated\b", re.IGNORECASE),
    re.compile(r"\bold content", re.IGNORECASE),
    re.compile(r"\bmismatch\b", re.IGNORECASE),
    re.compile(r"\bshould be\b", re.IGNORECASE),
    re.compile(r"\bwrong\b", re.IGNORECASE),
    re.compile(r"\bissue\b", re.IGNORECASE),
    re.compile(r"\bsync\b", re.IGNORECASE),
    re.compile(r"\bline \d+\b", re.IGNORECASE),
]
_ROLE_SIGNAL_PATTERNS = [
    re.compile(r"\s*-", re.IGNORECASE),
    re.compile(r"\b(video spc|motion graphics?|producer|rws|toin|lb|bal)\b", re.IGNORECASE),
]
_ACTOR_ROLE_HINTS = {
    "yuan": ("Animation", "Motion team usually flags animation issues, but may also note copy or VO problems."),
    "gideon": ("Animation", "Motion team usually flags animation issues, but may also note copy or VO problems."),
    "candice": ("Animation", "Capture-focused reviewer often flags UI or on-screen visual issues."),
    "fiona": ("Translation", "Copy-focused reviewer often flags translation, on-screen text, or VO wording issues."),
    "toin": ("Translation", "Translation/validation vendor usually flags translation or validation issues."),
    "lb": ("Translation", "Translation/validation vendor usually flags translation or validation issues."),
    "rws": ("Translation", "Translation/validation vendor usually flags translation or validation issues."),
    "bal": ("Animation", "Post-editing vendor usually flags animation, UI capture, and visual validation issues."),
}
_VENDOR_NAMES = {"toin": "Toin", "lb": "LB", "rws": "RWS", "bal": "BAL"}
_ANIMATION_ISSUE_PATTERNS = [
    re.compile(r"\banimat", re.IGNORECASE),
    re.compile(r"\bswipe\b", re.IGNORECASE),
    re.compile(r"\bbounce\b", re.IGNORECASE),
    re.compile(r"\bscreen\b", re.IGNORECASE),
    re.compile(r"\bdevice\b", re.IGNORECASE),
    re.compile(r"\blayout\b", re.IGNORECASE),
    re.compile(r"\balign", re.IGNORECASE),
    re.compile(r"\bui\b", re.IGNORECASE),
    re.compile(r"\bcapture\b", re.IGNORECASE),
]
_TRANSLATION_ISSUE_PATTERNS = [
    re.compile(r"\btranslation\b", re.IGNORECASE),
    re.compile(r"\bcopy\b", re.IGNORECASE),
    re.compile(r"\btext\b", re.IGNORECASE),
    re.compile(r"\bterm", re.IGNORECASE),
    re.compile(r"\bword", re.IGNORECASE),
    re.compile(r"\blocaliz", re.IGNORECASE),
    re.compile(r"\bsubtitle", re.IGNORECASE),
    re.compile(r"[一-龯ぁ-んァ-ヶ]", re.IGNORECASE),
]
_VOICE_OVER_ISSUE_PATTERNS = [
    re.compile(r"\bvo\b", re.IGNORECASE),
    re.compile(r"\bvoice ?over\b", re.IGNORECASE),
    re.compile(r"\bvoiceover\b", re.IGNORECASE),
    re.compile(r"\bscript\b", re.IGNORECASE),
    re.compile(r"\bpronunciation\b", re.IGNORECASE),
    re.compile(r"\baudio\b", re.IGNORECASE),
]
_SOURCE_ISSUE_PATTERNS = [
    re.compile(r"\bsource\b", re.IGNORECASE),
    re.compile(r"\bupstream\b", re.IGNORECASE),
    re.compile(r"\breference\b", re.IGNORECASE),
    re.compile(r"\bcapture info\b", re.IGNORECASE),
    re.compile(r"\bui capture\b", re.IGNORECASE),
    re.compile(r"\btrue ui\b", re.IGNORECASE),
    re.compile(r"\bscreenshot\b", re.IGNORECASE),
    re.compile(r"\basset\b", re.IGNORECASE),
    re.compile(r"\bplaceholder\b", re.IGNORECASE),
]
_GUIDANCE_PATTERNS = [
    re.compile(r"\b(?:fyi|note|reminder|please note|for reference|heads up|instruction|guidance)\b", re.IGNORECASE),
    re.compile(r"\blocale difference\b", re.IGNORECASE),
    re.compile(r"\b(?:expected|intentional) (?:locale|regional) (?:difference|behavior|wording)\b", re.IGNORECASE),
]
_LOCALE_DIFFERENCE_PATTERNS = [
    re.compile(r"\blocale difference\b", re.IGNORECASE),
    re.compile(r"\b(?:locale|regional|market)[ -]specific\b", re.IGNORECASE),
    re.compile(r"\bdiffers? (?:by|between|across) (?:locale|region|market|language)s?\b", re.IGNORECASE),
]
_RETAKE_IMPLICIT_PATTERNS = [
    re.compile(r"\bmodified\b", re.IGNORECASE),
    re.compile(r"\bupdated?\b", re.IGNORECASE),
    re.compile(r"\buploaded\b", re.IGNORECASE),
    re.compile(r"\bv\d+\b", re.IGNORECASE),
    re.compile(r"\bnew vo\b", re.IGNORECASE),
    re.compile(r"\bvo (?:and )?uploaded\b", re.IGNORECASE),
]
_SCRIPT_DIFFERENCE_PATTERNS = [
    re.compile(r"\bscript\b.*\bvo\b.*\bdiffer", re.IGNORECASE),
    re.compile(r"\bvo\b.*\bscript\b.*\bdiffer", re.IGNORECASE),
    re.compile(r"\bscript mismatch\b", re.IGNORECASE),
    re.compile(r"\bvo mismatch\b", re.IGNORECASE),
    re.compile(r"\bnot match(?:ing)?\b", re.IGNORECASE),
]

_PROMPT_TEMPLATE = """<system>
You are a localization QA tagging assistant.
Classify each spreadsheet row into one broad category tag and a few detail tags.
</system>

<rules>
- ALWAYS pick exactly one category_tag when the row clearly describes a real issue. If no issue, leave it empty.
- Allowed category_tag values: "Animation", "Translation", "Voice Over", "Source".
- detail_tags MUST be 1-3 values from the controlled summary tags below. Do not invent narrower tags such as grammar, spelling, typo, clipping, or formatting.
- Set is_issue to "yes", "no", or "unsure". For clear status updates, confirmations, or context-only rows, set is_issue to "no".
- If a Voice Over row explicitly requires another recording, include "retake".
- confidence MUST reflect real certainty from 0 to 1.
- CRITICAL NOISE FILTERING: Set `excluded: true` for generic status updates, "no issues found", and done confirmations. Keep useful reminders, guidance, and locale-difference context with category_tag "Source", is_issue "no", excluded false.
- To drastically reduce manual review, ALWAYS try to confidently set `excluded: true` or `excluded: false`. Set `review_required: true` ONLY in extremely ambiguous cases where a critical issue might be missed.
- If is_issue is "no", category_tag is normally empty. The only exception is useful source context, reminders, instructions, or locale differences: use category_tag "Source" with detail tag "guidance" or "locale difference" and excluded false.
- When classifying a batch, if a row is clearly independent, evaluate it independently. If it seems to be part of a conversation, try to infer context.
- review_reason MUST briefly explain why human review is needed (only if review_required is true).
- rationale MUST be a short explanation grounded in the exact row text.
- ALWAYS reuse existing detail tag wording when relevant. Keep detail tags compact.
- ALWAYS use 'Workflow Step' and 'Item Type' data for inference. If 'Item Type' is 'Voice Over', prioritize 'Voice Over' as category_tag.
</rules>

<context>
Common detail_tags patterns (use these when applicable):
- Translation: validation, terminology, locale difference, ui text, instructions
- Voice Over: validation, script mismatch, audio quality, pronunciation, pacing, retake
- Animation: validation, post editing, ui capture, motion timing, layout
- Source: validation, source mismatch, guidance, locale difference, source asset

Vendor constraints:
- Toin, LB, and RWS are translation vendors. Their rows usually concern Translation or Voice Over validation. Never create a grammar tag for them.
- BAL is a post-editing vendor. Its rows usually concern Animation, UI capture, motion timing, layout, or visual validation. Never create a grammar tag for BAL.
- Vendor identity is only a prior. The row text determines the category.

Reviewer role hints:
{reviewer_role_hints}

Relevant human-reviewed examples:
{relevant_feedback}

Relevant distilled review rules:
{distilled_guidance}
</context>

<rows>
{rows_json}
</rows>

Return ONLY raw JSON mapping row_key to the following shape. Do not include reasoning, markdown, or code fences:
{{
    "Sheet::2": {{
    "is_issue": "yes",
    "category_tag": "Translation",
    "detail_tags": ["terminology", "validation"],
    "confidence": 0.86,
    "excluded": false,
    "review_required": false,
    "review_reason": "",
    "rationale": "Terminology mismatch in localized subtitle text.",
    "issue_source": "RWS"
  }}
}}
"""


_CRITICAL_CELL_NAMES = {
    "workflow step", "item type", "description/ comment", "description / comment",
    "comment", "comment (2)", "comment by", "response", "response (2)",
    "response by", "response by (2)", "response by (3)", "status", "final status",
}


def _compact_cells(cells: object) -> dict[str, str]:
    if not isinstance(cells, dict):
        return {}
    compact: dict[str, str] = {}
    seen_values: set[str] = set()
    for raw_key, raw_value in cells.items():
        key = str(raw_key or "").strip()
        value = re.sub(r"\s+", " ", str(raw_value or "").replace("\u200b", " ")).strip()
        if not key or not value or value in {"-", "—"}:
            continue
        normalized_value = value.casefold()
        if key.casefold() not in _CRITICAL_CELL_NAMES and normalized_value in seen_values:
            continue
        compact[key] = value
        seen_values.add(normalized_value)
    return compact


def _dedupe_lines(value: str) -> str:
    seen: set[str] = set()
    lines: list[str] = []
    for line in str(value or "").splitlines():
        normalized = re.sub(r"\s+", " ", line).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        lines.append(normalized)
    return "\n".join(lines) or "None"


def _batch_input(batch: list[dict]) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for row in batch:
        key = _row_key(row)
        rows[key] = _compact_cells(row.get("cells", {}))
    return rows


def _row_key(row: dict) -> str:
    return f"{row.get('sheet', '')}::{row.get('row_index', 0)}"


def _row_text(row: dict) -> str:
    cells = row.get("cells", {}) or {}
    if isinstance(cells, dict):
        return " ".join(str(value or "").strip() for value in cells.values() if str(value or "").strip())
    return str(cells or "").strip()


def _cell_value(cells: dict, *names: str) -> str:
    for name in names:
        value = cells.get(name)
        if str(value or "").strip():
            return str(value).strip()
    return ""


def _reviewer_role_hints() -> str:
    return "\n".join(
        f"- {name.title()}: {hint}"
        for name, (_, hint) in _ACTOR_ROLE_HINTS.items()
    )


def _clean_json_response(response_text: str) -> str:
    start_brace = response_text.find('{')
    start_bracket = response_text.find('[')

    start_idx = start_brace if start_brace != -1 else start_bracket
    if start_brace != -1 and start_bracket != -1:
        start_idx = min(start_brace, start_bracket)

    end_brace = response_text.rfind('}')
    end_bracket = response_text.rfind(']')

    end_idx = end_brace if end_brace != -1 else end_bracket
    if end_brace != -1 and end_bracket != -1:
        end_idx = max(end_brace, end_bracket)

    if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
        return response_text[start_idx:end_idx + 1]
    return response_text.strip()


async def _predict_batch(batch: list[dict]) -> dict:
    try:
        relevant_feedback = feedback_retriever.get_relevant_feedback(batch)
    except Exception as exc:
        logger.warning("Failed to retrieve feedback examples for auto-tagging: %s", exc)
        relevant_feedback = "None"
    if not relevant_feedback:
        relevant_feedback = "None"
    relevant_feedback = _dedupe_lines(relevant_feedback)

    try:
        distilled_guidance = feedback_retriever.get_relevant_distilled_rules(batch)
    except Exception as exc:
        logger.warning("Failed to retrieve distilled guidance for auto-tagging: %s", exc)
        distilled_guidance = "None"
    if not distilled_guidance:
        distilled_guidance = "None"
    distilled_guidance = _dedupe_lines(distilled_guidance)

    prompt = _PROMPT_TEMPLATE.format(
        rows_json=json.dumps(_batch_input(batch), ensure_ascii=False, separators=(",", ":")),
        reviewer_role_hints=_reviewer_role_hints(),
        relevant_feedback=relevant_feedback,
        distilled_guidance=distilled_guidance,
    )

    max_retries = 3
    current_prompt = prompt
    for attempt in range(max_retries):
        try:
            response_text = await llm_client.generate(current_prompt)
            clean_text = _clean_json_response(response_text)
            parsed_json = json.loads(clean_text)

            if not isinstance(parsed_json, dict):
                raise ValueError(f"Expected a JSON object mapping row_key to tags, got {type(parsed_json).__name__}")

            return parsed_json
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"JSON parsing/validation failed on attempt {attempt + 1}: {e}")
            error_msg = f"Extraction or validation failed: {e}. Please ensure you output valid JSON starting with {{."
            current_prompt += f"\n\n<error>\n{error_msg}\nYour previous response:\n{response_text}\n</error>\nPlease try again and output valid JSON only."
        except llm_client.LLMQuotaExceededError as e:
            logger.warning("Skipping auto-tag batch because Gemini quota is exhausted: %s", e)
            raise
        except Exception as e:
            logger.error("Error calling LLM in auto_tagger: %s", e)
            raise

    return {}


async def _predict_batch_adaptively(batch: list[dict], predict_once) -> tuple[dict, list[dict]]:
    try:
        return await predict_once(batch), []
    except llm_client.LLMQuotaExceededError as exc:
        logger.warning("Skipping %s auto-tag row(s) because Gemini quota is unavailable: %s", len(batch), exc)
        return {}, batch
    except Exception as exc:
        if len(batch) > 1:
            midpoint = len(batch) // 2
            logger.warning(
                "Auto-tag batch of %s row(s) failed; retrying as %s and %s row(s): %s",
                len(batch),
                midpoint,
                len(batch) - midpoint,
                exc,
            )
            left_predictions, left_failed = await _predict_batch_adaptively(batch[:midpoint], predict_once)
            right_predictions, right_failed = await _predict_batch_adaptively(batch[midpoint:], predict_once)
            return {**left_predictions, **right_predictions}, [*left_failed, *right_failed]

        last_error = exc
        for attempt in range(1, AUTO_TAG_LEAF_ATTEMPTS):
            try:
                return await predict_once(batch), []
            except llm_client.LLMQuotaExceededError as quota_exc:
                last_error = quota_exc
                break
            except Exception as retry_exc:
                last_error = retry_exc
                logger.warning(
                    "Auto-tag retry %s/%s failed for row %s: %s",
                    attempt + 1,
                    AUTO_TAG_LEAF_ATTEMPTS,
                    _row_key(batch[0]),
                    retry_exc,
                )

        logger.error("Skipping auto-tag row %s after retries: %s", _row_key(batch[0]), last_error)
        return {}, batch


def _sanitize_category(value: str) -> str:
    normalized = str(value or "").strip()
    for category in ALLOWED_CATEGORY_TAGS:
        if normalized.lower() == category.lower():
            return category
    alias_map = {
        "copy": "Translation",
        "translation": "Translation",
        "voiceover": "Voice Over",
        "voice over": "Voice Over",
        "vo": "Voice Over",
        "motion": "Animation",
        "animation": "Animation",
        "source": "Source",
        "upstream": "Source",
    }
    return alias_map.get(normalized.lower(), "")


def _sanitize_detail_tags(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    cleaned = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        cleaned.append(text)
    return list(dict.fromkeys(cleaned))[:5]


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _coerce_confidence(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _normalize_is_issue(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"yes", "y", "true", "1", "issue"}:
        return "yes"
    if normalized in {"no", "n", "false", "0", "not issue", "not_issue", "no issue", "context", "noise"}:
        return "no"
    if normalized in {"unsure", "unknown", "maybe", "tbd", "?"}:
        return "unsure"
    return ""


def _is_low_signal_confirmation(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    token_count = len(re.findall(r"[a-z0-9]+", normalized))
    if token_count > 8:
        return False
    return any(pattern.search(normalized) for pattern in _LOW_SIGNAL_CONFIRMATION_PATTERNS)


def _low_signal_bucket(row: dict) -> str | None:
    cells = row.get("cells", {}) or {}
    comment_text = _cell_value(cells, "Comment", "Comment (2)")
    response_text = _cell_value(cells, "Response", "Response (2)")
    actor_text = " ".join(filter(None, [
        _cell_value(cells, "Response by", "Response by (2)", "Response by (3)"),
        _cell_value(cells, "Comment by"),
    ])).strip()
    status_text = _cell_value(cells, "Status", "FINAL STATUS")
    item_type = _cell_value(cells, "Item Type")

    normalized = str(comment_text or "").strip().lower()
    if not normalized:
        return None
    token_count = len(re.findall(r"[a-z0-9]+", normalized))
    if token_count > 12:
        return None

    combined_context = " ".join(filter(None, [comment_text, response_text, actor_text, status_text, item_type]))
    if any(pattern.search(comment_text) for pattern in _SPECIFIC_ISSUE_PATTERNS):
        return None
    if any(pattern.search(combined_context) for pattern in _WORKFLOW_STATUS_PATTERNS):
        return "workflow-status"
    if any(pattern.search(comment_text) for pattern in _LOW_SIGNAL_CONFIRMATION_PATTERNS):
        if actor_text and any(pattern.search(actor_text) for pattern in _ROLE_SIGNAL_PATTERNS) and not response_text:
            return "workflow-status"
        return "context-signoff"
    return None


def _actor_prior_category(row: dict) -> str | None:
    cells = row.get("cells", {}) or {}
    actor_text = " ".join(filter(None, [
        _cell_value(cells, "Response by", "Response by (2)", "Response by (3)"),
        _cell_value(cells, "Comment by"),
    ])).lower()
    if not actor_text:
        return None
    for actor_name, (category, _) in _ACTOR_ROLE_HINTS.items():
        if actor_name in actor_text:
            return category
    return None


def _actor_vendor(row: dict) -> str:
    cells = row.get("cells", {}) or {}
    actor_text = " ".join(filter(None, [
        _cell_value(cells, "Response by", "Response by (2)", "Response by (3)"),
        _cell_value(cells, "Comment by"),
    ])).lower()
    for token, vendor in _VENDOR_NAMES.items():
        if re.search(rf"\b{re.escape(token)}\b", actor_text):
            return vendor
    return ""


def _contextual_source_tags(row: dict) -> list[str]:
    text = _combined_row_text(row)
    tags: list[str] = []
    if any(pattern.search(text) for pattern in _LOCALE_DIFFERENCE_PATTERNS):
        tags.append("locale difference")
    if any(pattern.search(text) for pattern in _GUIDANCE_PATTERNS):
        tags.append("guidance")
    return tags


def _summarize_detail_tags(category: str, values: list[str]) -> list[str]:
    text = " ".join(values).lower()
    mapped: list[str] = []
    rules = {
        "validation": ("validation", "grammar", "spelling", "typo", "proofread", "check", "missed", "incorrect", "wrong"),
        "terminology": ("terminology", "term", "naming"),
        "locale difference": ("locale", "regional", "market-specific", "language difference"),
        "ui text": ("ui text", "copy", "subtitle", "vtt", "text change", "truncation"),
        "instructions": ("instruction", "guideline", "not follow"),
        "script mismatch": ("script mismatch", "script", "vo text"),
        "audio quality": ("audio quality", "noise", "volume", "loudness", "bgm", "music"),
        "pronunciation": ("pronunciation", "accent", "intonation"),
        "pacing": ("pacing", "pace", "pause"),
        "retake": ("retake", "outdated"),
        "post editing": ("post edit", "post-edit", "render", "frame", "clipping", "formatting", "color"),
        "ui capture": ("ui capture", "capture", "screen", "device", "icon"),
        "motion timing": ("motion", "animation", "timing", "sync", "transition", "easing", "hold"),
        "layout": ("layout", "align", "position", "spacing", "overlap"),
        "source mismatch": ("source mismatch", "upstream", "reference", "true ui", "screenshot", "capture", "placeholder", "outdated", "wrong version"),
        "guidance": ("guidance", "reminder", "instruction", "fyi", "note", "reference"),
        "source asset": ("source asset", "asset", "deliverable", "file", "version"),
    }
    allowed = SUMMARY_DETAIL_TAGS.get(category, ())
    if not allowed:
        return []
    for tag in allowed:
        if any(term in text for term in rules[tag]):
            mapped.append(tag)
    if not mapped and values:
        mapped.append("validation" if "validation" in allowed else allowed[0])
    return mapped[:3]


def _issue_signal_categories(row: dict) -> set[str]:
    cells = row.get("cells", {}) or {}
    issue_text = " ".join(filter(None, [
        _cell_value(cells, "Comment", "Comment (2)", "Description/ Comment", "Description / Comment"),
        _cell_value(cells, "Response", "Response (2)"),
        _cell_value(cells, "Item Type"),
    ]))
    categories: set[str] = set()
    if any(pattern.search(issue_text) for pattern in _ANIMATION_ISSUE_PATTERNS):
        categories.add("Animation")
    if any(pattern.search(issue_text) for pattern in _TRANSLATION_ISSUE_PATTERNS):
        categories.add("Translation")
    if any(pattern.search(issue_text) for pattern in _VOICE_OVER_ISSUE_PATTERNS):
        categories.add("Voice Over")
    if any(pattern.search(issue_text) for pattern in _SOURCE_ISSUE_PATTERNS):
        categories.add("Source")
    return categories


def _combined_row_text(row: dict) -> str:
    cells = row.get("cells", {}) or {}
    return " ".join(
        filter(
            None,
            [
                _cell_value(cells, "Comment", "Comment (2)", "Description/ Comment", "Description / Comment"),
                _cell_value(cells, "Response", "Response (2)"),
                _cell_value(cells, "Response by", "Response by (2)", "Response by (3)"),
                _cell_value(cells, "Comment by"),
                _cell_value(cells, "Item Type"),
                _cell_value(cells, "Status", "FINAL STATUS"),
            ],
        )
    )


def _should_add_retake_needed(row: dict, category_tag: str, detail_tags: list[str]) -> bool:
    if category_tag != "Voice Over":
        return False
    normalized_tags = {str(tag or "").strip().lower() for tag in detail_tags}
    if "retake needed" in normalized_tags or "vo-retake" in normalized_tags or "outdated" in normalized_tags:
        return False

    combined_text = _combined_row_text(row)
    if not combined_text:
        return False

    explicit = retake_detector.detect_explicit_retake(combined_text)
    if explicit.get("retake_explicit") == "yes":
        return True

    has_script_difference = (
        "script mismatch" in normalized_tags
        or any(pattern.search(combined_text) for pattern in _SCRIPT_DIFFERENCE_PATTERNS)
    )
    has_retake_followup = any(pattern.search(combined_text) for pattern in _RETAKE_IMPLICIT_PATTERNS)
    return has_script_difference and has_retake_followup


def _non_issue_defaults(reason: str, confidence: float, existing: RowTag) -> dict:
    return {
        "tags": existing.tags,
        "category_tag": "",
        "detail_tags": [],
        "confidence": min(confidence or REVIEW_THRESHOLD, 0.98),
        "rationale": existing.rationale,
        "excluded": True,
        "is_noise": existing.is_noise,
        "review_required": False,
        "review_reason": "",
        "is_issue": "no",
        "taxonomy_category": "",
        "taxonomy_tags": [],
        "taxonomy_confidence": 0.0,
        "taxonomy_rationale": reason,
    }


def _apply_predictions(doc_tags: DocTags, predictions: dict, rows_by_key: dict[str, dict]) -> None:
    for key, pred in predictions.items():
        if not isinstance(pred, dict):
            continue
        department_tag = str(pred.get("department") or "").strip()
        category_tag = _sanitize_category(pred.get("category_tag") or pred.get("category") or pred.get("department"))
        detail_tags = _sanitize_detail_tags(pred.get("detail_tags") or pred.get("taxonomy_tags") or pred.get("tags"))
        confidence = _coerce_confidence(pred.get("confidence"))
        excluded = _coerce_bool(pred.get("excluded"))
        is_issue = _normalize_is_issue(pred.get("is_issue"))
        rationale = str(pred.get("rationale") or "").strip()
        review_required = _coerce_bool(pred.get("review_required")) or confidence < REVIEW_THRESHOLD or not category_tag
        review_reason = str(pred.get("review_reason") or "").strip()
        if review_required and not review_reason:
            review_reason = "Low confidence or ambiguous category."

        existing = doc_tags.rows.get(key, RowTag())
        row = rows_by_key.get(key, {})
        issue_source = _actor_vendor(row) or str(pred.get("issue_source") or existing.issue_source or "").strip()
        low_signal_bucket = _low_signal_bucket(row)
        if low_signal_bucket == "context-signoff":
            updated = existing.model_copy(update=_non_issue_defaults(
                "Generic no-comment / no-issue confirmation; auto-marked as not an issue.",
                confidence,
                existing,
            ))
            updated.rationale = rationale or "Generic no-comment / no-issue confirmation."
            doc_tags.rows[key] = updated
            continue
        elif low_signal_bucket == "workflow-status":
            updated = existing.model_copy(update=_non_issue_defaults(
                "Generic workflow status update; auto-marked as not an issue.",
                confidence,
                existing,
            ))
            updated.rationale = rationale or "Generic workflow status update."
            doc_tags.rows[key] = updated
            continue
        else:
            actor_prior = _actor_prior_category(row)
            issue_signal_categories = _issue_signal_categories(row)
            if actor_prior and not category_tag and actor_prior in issue_signal_categories:
                category_tag = actor_prior
                review_required = True
                confidence = min(confidence or 0.7, 0.72)
                review_reason = f"Reviewer role suggests {actor_prior}, but keep human review because the text is still ambiguous."
            elif actor_prior and category_tag and category_tag != actor_prior and actor_prior in issue_signal_categories and confidence < 0.9:
                review_required = True
                review_reason = (
                    f"Reviewer role leans {actor_prior}, but the row was tagged as {category_tag}; verify manually."
                )

        detail_tags = _summarize_detail_tags(category_tag, detail_tags)

        if is_issue == "no":
            context_tags = _contextual_source_tags(row)
            if context_tags:
                updated = existing.model_copy(update={
                    "tags": ["Source"],
                    "category_tag": "Source",
                    "detail_tags": context_tags,
                    "confidence": confidence or existing.confidence or 0.9,
                    "rationale": rationale or "Useful source guidance or locale-specific context.",
                    "excluded": False,
                    "is_noise": existing.is_noise,
                    "review_required": False,
                    "review_reason": "",
                    "is_issue": "no",
                    "issue_source": issue_source or "Source Asset",
                    "taxonomy_category": "Source",
                    "taxonomy_tags": context_tags,
                    "taxonomy_confidence": confidence or existing.taxonomy_confidence or 0.9,
                    "taxonomy_rationale": rationale or "Useful source guidance or locale-specific context.",
                })
                doc_tags.rows[key] = updated
                continue
            updated = existing.model_copy(update=_non_issue_defaults(
                rationale or "Model marked this row as not an issue.",
                confidence,
                existing,
            ))
            updated.rationale = rationale or updated.rationale
            doc_tags.rows[key] = updated
            continue

        if is_issue == "unsure":
            review_required = True
            review_reason = review_reason or "Model is unsure whether this row is a real issue."

        # Preserve only explicit noise/archive rows across future auto-tag runs.
        # Legacy excluded-only rows should not keep auto-hiding forever.
        preserved_excluded = existing.is_noise or excluded

        if _should_add_retake_needed(row, category_tag, detail_tags):
            detail_tags = list(dict.fromkeys([*detail_tags, "retake"]))[:3]

        updated = existing.model_copy(update={
            "tags": [department_tag] if department_tag else ([category_tag] if category_tag else existing.tags),
            "category_tag": category_tag or existing.category_tag,
            "detail_tags": detail_tags or existing.detail_tags,
            "confidence": confidence or existing.confidence,
            "rationale": rationale or existing.rationale,
            "excluded": preserved_excluded and not department_tag and not category_tag and not detail_tags,
            "is_noise": existing.is_noise,
            "review_required": review_required,
            "review_reason": review_reason if review_required else "",
            "is_issue": is_issue or existing.is_issue,
            "issue_source": issue_source,
            "taxonomy_category": category_tag or existing.taxonomy_category,
            "taxonomy_tags": detail_tags or existing.taxonomy_tags,
            "taxonomy_confidence": confidence or existing.taxonomy_confidence,
            "taxonomy_rationale": rationale or existing.taxonomy_rationale,
        })
        doc_tags.rows[key] = updated


async def auto_tag_doc(raw_doc_dict: dict, rules: FilterRules | None = None) -> DocTags:
    if rules is None:
        rules = rules_store.load()

    parsed = quip_parser.parse_dict(raw_doc_dict, rules)
    doc_id = parsed.doc_id
    doc_tags = tags_store.load(doc_id)
    if not parsed.table_rows:
        return doc_tags

    batches = [
        parsed.table_rows[i:i + AUTO_TAG_BATCH_SIZE]
        for i in range(0, len(parsed.table_rows), AUTO_TAG_BATCH_SIZE)
    ]

    batch_semaphore = asyncio.Semaphore(max(1, settings.auto_tag_max_concurrency))

    async def predict_with_limit(batch: list[dict]) -> dict:
        async with batch_semaphore:
            return await _predict_batch(batch)

    results = await asyncio.gather(
        *(_predict_batch_adaptively(batch, predict_with_limit) for batch in batches),
    )
    predictions: dict = {}
    failed_rows: list[dict] = []
    for batch_predictions, batch_failed_rows in results:
        predictions.update(batch_predictions)
        failed_rows.extend(batch_failed_rows)

    rows_by_key = {_row_key(row): row for row in parsed.table_rows}
    _apply_predictions(doc_tags, predictions, rows_by_key)

    if failed_rows:
        logger.warning(
            "Auto-tagging completed with %s/%s row(s) skipped; successful predictions will be preserved.",
            len(failed_rows),
            len(parsed.table_rows),
        )

    tags_store.save(doc_tags)
    return doc_tags
