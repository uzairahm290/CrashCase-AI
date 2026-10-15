from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime config comes from env vars (see .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="CC_", extra="ignore")

    # Infra
    database_url: str = "sqlite:///./crashcase.db"
    redis_url: str = "redis://localhost:6379/0"
    # When true, claims are processed inside the API request (tests / local dev without a worker)
    inline_processing: bool = False
    cors_origins: str = "http://localhost:3000"
    # Fill an empty claim index with synthetic claims at API start-up. Turn off when several
    # API replicas start together (ECS); seed once with scripts/seed_claims.py instead.
    auto_seed: bool = True

    # Storage: "local" or "s3"
    storage_backend: str = "local"
    upload_dir: Path = Path("./data/uploads")
    s3_bucket: str = ""

    # Models: "stub" works with no weights; "yolo" needs trained weights
    detector_backend: str = "stub"
    # Local path, or an MLflow URI such as models:/crashcase-damage-seg@champion
    damage_weights: str = "models/damage-seg.pt"
    parts_weights: str = ""
    embedder_backend: str = "histogram"  # "histogram" or "clip"
    embed_dim: int = 512

    # Retrieval: "memory" or "pgvector"
    index_backend: str = "memory"
    top_k: int = 5

    # Quality gate
    min_blur_score: float = 60.0
    min_brightness: float = 40.0
    max_brightness: float = 225.0

    # Fraud
    duplicate_hash_distance: int = 18  # out of 256 bits

    # Report LLM (Groq, OpenAI-compatible). Empty key -> template report.
    llm_api_key: str = ""
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "llama-3.1-8b-instant"
    prompt_version: str = "v1"
    # Langfuse tracing of report generation (optional)
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # Drift: share of monitored columns that must drift before retraining is suggested
    drift_share_threshold: float = 0.3

    cost_table_path: Path = Path("configs/cost_table.yaml")
    worker_metrics_port: int = 9100


@lru_cache
def get_settings() -> Settings:
    return Settings()
