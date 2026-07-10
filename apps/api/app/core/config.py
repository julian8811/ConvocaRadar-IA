import logging

from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "ConvocaRadar IA"
    database_url: str = "sqlite:///./convocaradar.db"
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    llm_provider: str = "local"
    llm_api_base: str = "https://api.openai.com/v1"
    llm_api_key: str | None = None
    llm_model: str = "gpt-4.1-mini"
    chat_model: str = "gpt-4.1-mini"
    embedding_model: str = ""
    embedding_dimensions: int = 64
    llm_timeout_seconds: int = 45
    bootstrap_sources_on_startup: bool = True
    bootstrap_sources_blocking: bool = False
    bootstrap_source_keys: str = "grants-gov-rss,grants-gov,innpulsa,minciencias,nsf-funding-rss"
    sentry_dsn: str | None = None
    sentry_send_default_pii: bool = False
    scraping_user_agent: str = "ConvocaRadarBot/0.1"
    scraping_timeout_seconds: int = 180
    scraping_max_source_seconds: int = 180
    scraping_max_concurrency: int = 5
    scraping_closing_soon_days: int = 10
    internal_api_key: str = Field(min_length=32)
    reset_token_secret: str | None = None
    sedia_api_key: str = "SEDIA"
    per_connector_timeout_seconds: float = 180
    storage_backend: str = "local"
    storage_dir: str = "./storage"
    max_upload_bytes: int = 10_000_000
    s3_endpoint_url: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket: str = "convocaradar"
    s3_region: str = "us-east-1"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "alerts@convocaradar.local"
    smtp_use_tls: bool = True
    frontend_url: str = "http://localhost:3000"
    backend_url: str = "http://localhost:8000"
    # PR2: Redis / worker dispatch
    redis_url: str | None = None
    worker_max_concurrency: int = 4
    rate_limit_requests_per_minute: int = 120
    rate_limit_window_seconds: int = 60

    @computed_field  # type: ignore[prop-decorator]
    @property
    def bootstrap_source_key_list(self) -> list[str]:
        return [item.strip() for item in self.bootstrap_source_keys.split(",") if item.strip()]

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.chat_model:
        settings.chat_model = settings.llm_model
    return settings


def check_production_sqlite(app_env: str | None = None, database_url: str | None = None) -> None:
    """Log a warning when DATABASE_URL uses SQLite in a production environment.

    SQLite is not safe for concurrent production workloads — it can cause
    data corruption under concurrent writes. This check warns operators who
    forget to configure a real database in production.

    Call this once during application startup.
    """
    env = (app_env or get_settings().app_env).strip().lower()
    db_url = (database_url or get_settings().database_url).strip().lower()
    if env == "production" and "sqlite" in db_url:
        logger.warning(
            "DATABASE_URL uses SQLite in APP_ENV=production. "
            "SQLite is NOT safe for production — concurrent writes can "
            "cause data corruption. Configure PostgreSQL via DATABASE_URL "
            "in your environment."
        )


def effective_llm_provider(provider: str | None = None) -> str:
    value = (provider or get_settings().llm_provider).strip().lower()
    if value in {"mock", "local", ""}:
        return "local"
    return value
