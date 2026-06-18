"""Persist global filter rules to disk so they survive restarts."""
from pathlib import Path
from ..config import settings
from ..models.rules import FilterRules, DEFAULT_RULES


_path = settings.rules_path


def load() -> FilterRules:
    if not _path.exists():
        return DEFAULT_RULES.model_copy()
    return FilterRules.model_validate_json(_path.read_text(encoding="utf-8"))


def save(rules: FilterRules) -> Path:
    _path.write_text(rules.model_dump_json(indent=2), encoding="utf-8")
    return _path


def reset_to_default() -> FilterRules:
    save(DEFAULT_RULES.model_copy())
    return load()
