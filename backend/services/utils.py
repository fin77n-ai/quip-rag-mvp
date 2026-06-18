"""Common utility functions shared across services."""

from __future__ import annotations

from collections import Counter
from typing import Any


def safe_get(d: dict, key: str, default: Any = "") -> Any:
    """Safely get value from dict with default."""
    return d.get(key, default)


def safe_str(value: Any, default: str = "") -> str:
    """Convert value to string safely."""
    return str(value) if value is not None else default


def top_counts(counter: Counter, limit: int = 100) -> list[dict[str, Any]]:
    """
    Convert Counter to sorted list of dicts with 'value' and 'count' keys.

    Args:
        counter: Counter object to convert
        limit: Maximum number of items to return

    Returns:
        List of dicts sorted by count (descending)
    """
    return [
        {"value": value, "count": count}
        for value, count in counter.most_common(limit)
    ]


def extract_metadata_field(meta: dict, key: str, default: str = "") -> str:
    """
    Extract a field from metadata dict with fallback.

    Args:
        meta: Metadata dictionary
        key: Key to extract
        default: Default value if key not found

    Returns:
        String value or default
    """
    value = meta.get(key)
    if value is None:
        return default
    return str(value).strip()


def chunk_list(items: list, chunk_size: int) -> list[list]:
    """
    Split a list into chunks of specified size.

    Args:
        items: List to chunk
        chunk_size: Size of each chunk

    Returns:
        List of chunks
    """
    return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]
