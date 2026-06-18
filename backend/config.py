from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    data_dir: Path = Path("./data")

    # Vector stores
    lance_dir: Path = Path("./data/vector_stores/lance")

    # Analytics
    duckdb_path: Path = Path("./data/analytics/analytics.duckdb")

    # Sources
    quip_dir: Path = Path("./data/sources/quip")

    # Processed data
    row_tags_dir: Path = Path("./data/processed/row_tags")
    staging_db_path: Path = Path("./data/processed/staging.db")

    # Feedback
    tag_feedback_path: Path = Path("./data/feedback/tag_feedback.jsonl")
    taxonomy_path: Path = Path("./data/feedback/taxonomy.json")

    # Config
    rules_path: Path = Path("./data/config/filter_rules.json")

    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "mps"

    duck_lance_enabled: bool = True
    rerank_enabled: bool = True
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_candidate_multiplier: int = 4

    mmr_enabled: bool = True
    mmr_lambda_default: float = 0.7
    keyword_recall_enabled: bool = True

    llm_model: str = "gemini-3.1-pro-preview"
    llm_use_floodgate: bool = True
    llm_max_concurrency: int = 2
    llm_timeout_seconds: float = 300.0
    llm_min_interval_seconds: float = 1.0
    auto_tag_max_concurrency: int = 2

    frontend_origin: str = "http://localhost:5173"

    quip_token: str | None = None
    quip_base_url: str = "https://platform.quip.com/1"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()

# Create directory structure
for _d in (
    settings.lance_dir,
    settings.quip_dir,
    settings.row_tags_dir,
    settings.duckdb_path.parent,  # analytics/
    settings.tag_feedback_path.parent,  # feedback/
    settings.rules_path.parent,  # config/
):
    _d.mkdir(parents=True, exist_ok=True)
