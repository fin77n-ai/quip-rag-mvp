import json
import logging
import re

import numpy as np

from . import llm_client


logger = logging.getLogger(__name__)


async def generate_search_synonyms(original_query: str) -> list[str]:
    """Use the LLM to expand a search query with concise, closely related variants."""
    prompt = f"""You are a technical search assistant. Given a user's search query, generate 3 to 4 alternative search queries (synonyms, technical terms, both English and Chinese translations) that are highly relevant to find solutions or issues in QA spreadsheets or test cases.
Keep them concise, focusing strictly on search keywords.

User Query: {original_query}

Format your output strictly as a JSON list of strings, for example:
["synonym 1", "synonym 2", "synonym 3"]
Do not output any markdown formatting like ```json or any explanations. Just the raw JSON array.
"""
    try:
        response_text = await llm_client.generate(prompt)
        cleaned = re.sub(r"```json|```", "", response_text).strip()
        synonyms = json.loads(cleaned)
        if isinstance(synonyms, list):
            return [s.strip() for s in synonyms if s.strip()]
    except Exception as e:
        logger.warning(f"Failed to generate synonyms: {e}")
    return []


def compute_cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    v1, v2 = np.array(vec1), np.array(vec2)
    norm1, norm2 = np.linalg.norm(v1), np.linalg.norm(v2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return float(np.dot(v1, v2) / (norm1 * norm2))
