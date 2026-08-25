from functools import lru_cache

from pydantic_settings import BaseSettings

try:
    from pydantic_settings import ConfigDict  # type: ignore
except ImportError:  # pragma: no cover - fallback for pydantic_settings<2.7 compat
    from pydantic import ConfigDict  # type: ignore


class Settings(BaseSettings):
    app_name: str = "Learning Planner API"
    app_version: str = "0.1.0"
    debug: bool = True

    # Database
    database_url: str = "postgresql://postgres:postgres@localhost:5432/app"
    neo4j_url: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"
    neo4j_database: str = "neo4j"
    redis_url: str = "redis://localhost:6379/0"

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "learning-planner"
    minio_secure: bool = False

    # LLM
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"

    # Auth
    jwt_secret: str = "change-me-in-production-32chars-min"
    jwt_expire_days: int = 7
    jwt_algorithm: str = "HS256"

    # CORS
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000", "app://*"]

    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
