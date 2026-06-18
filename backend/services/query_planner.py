from dataclasses import dataclass, field
import json
import logging

from ..models.query import QueryFilters
from . import llm_client

logger = logging.getLogger(__name__)

@dataclass
class QueryPlan:
    intent: str
    route: str
    inferred_tags: list[str] = field(default_factory=list)
    sql_prompt: str | None = None

_ROUTER_PROMPT_TEMPLATE = """
<system>
You are a Semantic Router for a Query Planning system.
Your task is to classify the user's question into one of three intents:
1. "rag": The user is asking for specific content, context, explanations, or factual details (e.g. "What did they say about the button?", "How do I fix the translation issue?").
2. "sql": The user is asking for aggregate statistics, counts, or grouped metrics (e.g. "How many issues were found in France?", "Count the number of bugs per sprint", "Which locale had the most errors?").
3. "repeated": The user is specifically asking about recurring, common, or repeated issues across different contexts.

You must output ONLY a valid JSON object matching this schema:
{{
  "intent": "rag" | "sql" | "repeated",
  "reasoning": "A brief explanation of why this intent was chosen."
}}
</system>

<question>
{question}
</question>
"""

_SQL_PROMPT_TEMPLATE = """
<system>
You are a Text-to-SQL prompt generator. The user has asked an aggregate query that requires executing SQL against a DuckDB database.
The database schema has a table named `issues` with the following columns:
- `id` (VARCHAR): Unique identifier for the issue
- `doc_id` (VARCHAR): Document or Quip ID
- `sprint` (VARCHAR): Sprint name
- `category` (VARCHAR): Issue category (e.g., 'Animation', 'Translation', 'Voice Over')
- `sheet` (VARCHAR): Locale or language sheet
- `status` (VARCHAR): Current status
- `tags` (VARCHAR): Comma-separated list of tags
- `text` (VARCHAR): Description of the issue

Generate a SQL query that answers the user's question. Output ONLY the raw SQL query, no markdown formatting.
</system>

<question>
{question}
</question>
"""

def infer_tag_from_question(question: str) -> str | None:
    q = question.lower()
    if "copy" in q:
        return "Copy"
    if "motion" in q:
        return "Motion"
    if "source" in q:
        return "Source"
    if "untagged" in q or "未标" in q or "没标签" in q:
        return "(untagged)"
    return None

async def plan_query(question: str, filters: QueryFilters, trace_id: str | None = None) -> QueryPlan:
    inferred = infer_tag_from_question(question)
    inferred_tags = [] if not inferred or filters.tags else [inferred]

    # 1. Semantic Router Step
    prompt = _ROUTER_PROMPT_TEMPLATE.format(question=question)
    try:
        response_text = await llm_client.generate(prompt)
        # Extract JSON if embedded in text
        start_idx = response_text.find('{')
        end_idx = response_text.rfind('}')
        if start_idx != -1 and end_idx != -1:
            clean_json = response_text[start_idx:end_idx+1]
            router_result = json.loads(clean_json)
            intent = router_result.get("intent", "rag")
        else:
            intent = "rag"
    except Exception as e:
        logger.error(f"[TraceID: {trace_id}] Semantic router failed: {e}. Falling back to RAG.")
        intent = "rag"

    route_map = {
        "rag": "rag",
        "sql": "sql",
        "repeated": "analyze/repeated"
    }
    route = route_map.get(intent, "rag")

    # 2. Text-to-SQL Step (if sql intent)
    sql_prompt = None
    if intent == "sql":
        sql_gen_prompt = _SQL_PROMPT_TEMPLATE.format(question=question)
        try:
            sql_prompt = await llm_client.generate(sql_gen_prompt)
            sql_prompt = sql_prompt.strip().strip("```sql").strip("```").strip()
        except Exception as e:
            logger.error(f"[TraceID: {trace_id}] SQL generation failed: {e}")

    return QueryPlan(intent=intent, route=route, inferred_tags=inferred_tags, sql_prompt=sql_prompt)
