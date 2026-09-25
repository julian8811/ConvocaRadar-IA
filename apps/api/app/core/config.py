import logging

from functools import lru_cache
from typing import ClassVar

from pydantic import Field, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


logger = logging.getLogger(__name__)


PLACEHOLDERS = {"change-me", "changeme", "change_me", "replace_with", "replace-with", "password", "placeholder"}

class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "ConvocaRadar IA"
    database_url: str = "sqlite:///./convocaradar.db"
    postgres_password: str | None = Field(default=None, description="Postgres password — required in production, >=16 non-placeholder")
    minio_root_password: str | None = Field(default=None, description="MinIO password — required in production, >=16 non-placeholder")
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    llm_provider: str = "local"
    llm_api_base: str = "https://api.openai.com/v1"
    llm_api_key: str | None = None
    llm_model: str = "gpt-4.1-mini"
    chat_model: str = "gpt-4.1-mini"
    embedding_model: str = ""
    embedding_dimensions: int = 1024
    # ── T5 (fortalecer-201): AI gateway — Gemini primario, local fallback ──
    # Orden: Gemini (si hay key) → remoto genérico compatible (Codex/OpenAI
    # vía llm_* — solo si está configurado) → hash-local (siempre, sin key).
    # Sin GEMINI_API_KEY el gateway opera en local (cero costo) sin romper nada.
    # GEMINI_API_KEY es la vía primaria; como alias se acepta LLM_API_KEY
    # cuando LLM_PROVIDER=gemini (resuelto en app.core.ai_gateway — no hay
    # dos variables con el mismo rol).
    gemini_api_key: str | None = None
    gemini_api_base: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    gemini_embedding_model: str = "text-embedding-004"
    # Cuotas de llamadas REMOTAS por organización (caché y fallback local no
    # consumen cuota). Defaults conservadores de arranque — NO son política
    # final; ajustar por env según gasto observado. <=0 = cuota deshabilitada.
    ai_quota_embeddings_per_day: int = 500
    ai_quota_embeddings_per_month: int = 10000
    # Caché en memoria de embeddings (proceso local; se pierde al reiniciar).
    ai_embedding_cache_size: int = 1024
    ai_embedding_cache_ttl_seconds: int = 86400  # 24 h
    llm_timeout_seconds: int = 45
    bootstrap_sources_on_startup: bool = True
    bootstrap_sources_blocking: bool = False
    bootstrap_source_keys: str = "grants-gov-rss,grants-gov,innpulsa,minciencias,nsf-funding-rss"
    sentry_dsn: str | None = None
    sentry_send_default_pii: bool = False
    scraping_user_agent: str = (
        "Mozilla/5.0 (compatible; ConvocaRadarBot/1.0; +https://github.com/ConvocaRadar/ConvocaRadar-IA)"
    )
    scraping_timeout_seconds: int = 180
    scraping_max_source_seconds: int = 180
    scraping_max_concurrency: int = 6
    # ── T3 (fortalecer-201): per-tier sweep concurrency (reversible) ──────
    # Each tier gets its own semaphore; a shared global semaphore capped at
    # min(6, scraping_max_concurrency) keeps total load ≤ today's. Env unset
    # (None) → documented default 3/2/1 (sums to today's 6). Env set →
    # explicit opt-in, clamped to [1, global cap] so a typo can't exceed prod
    # load. Raising total load above 6 needs the min(6, …) cap change (code).
    scraping_max_concurrency_strategic: int | None = None
    scraping_max_concurrency_complementary: int | None = None
    scraping_max_concurrency_experimental: int | None = None
    scraping_closing_soon_days: int = 10
    scraping_proxy_list: list[str] = Field(
        default_factory=list,
        description="Comma-separated proxy URLs for rotation. "
                    "Format: http://user:pass@host:port,http://user:pass@host2:port",
    )
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
    smtp_from: str = "noreply@convocaradar.com"
    smtp_use_tls: bool = True
    resend_api_key: str | None = None
    resend_from: str = "Observatorio de Convocatorias <onboarding@resend.dev>"
    alert_default_recipient: str | None = None
    frontend_url: str = "http://localhost:3002"
    backend_url: str = "http://localhost:8000"
    app_timezone: str = "America/Bogota"
    rate_limit_requests_per_minute: int = 120
    rate_limit_window_seconds: int = 60
    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 1800
    scheduler_initial_delay_seconds: int = 30
    weekly_digest_interval_seconds: int = 604800
    # ── Extraction flags (022) ──────────────────────────────────────────
    extraction_cop_default: bool = True
    extraction_prompt_v4: bool = True
    extraction_detail_limit: int = 25
    extraction_year_min: int = 2024
    extraction_year_max: int = 2028
    extraction_llm_always: bool = False
    extraction_thin_threshold: int = 200
    extraction_missing_close_penalty: int = 10
    extraction_missing_funding_penalty: int = 5
    extraction_llm_cache_size: int = 256
    # ── 023 flags (reversible, off-default) ───────────────────────────────
    extraction_batch_enabled: bool = False
    extraction_spa_retry: bool = False
    throttle_max_per_day: int = 150
    # ── faculty match flags (PR1) ─────────────────────────────────────
    faculty_match_enabled: bool = True
    axis_match_threshold: float = 0.35
    llm_classification_enabled: bool = False
    faculty_thresholds: str = ""  # e.g. "F1:0.40,F4:0.32" reversible per-faculty override

    @computed_field  # type: ignore[prop-decorator]
    @property
    def faculty_threshold_map(self) -> dict[str, float]:
        out: dict[str, float] = {}
        if self.faculty_thresholds:
            for part in self.faculty_thresholds.split(","):
                if ":" not in part:
                    continue
                k, v = part.split(":", 1)
                k = k.strip().upper()
                try:
                    out[k] = float(v.strip())
                except ValueError:
                    continue
        return out

    @field_validator("jwt_secret", "internal_api_key", mode="after")
    @classmethod
    def _strong_secret(cls, v: str) -> str:
        if v is not None and isinstance(v, str):
            if len(v) < 16:
                raise ValueError("secret must be >=16 characters")
        return v

    @field_validator("postgres_password", "minio_root_password", mode="after")
    @classmethod
    def _strong_optional_secret(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if len(v) < 16:
            raise ValueError("secret must be >=16 characters")
        return v

    @field_validator("reset_token_secret", mode="after")
    @classmethod
    def _reset_token_secret_strength(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if len(v) < 16:
            raise ValueError("secret must be >=16 characters")
        return v

    @model_validator(mode="after")
    def _prod_guards(self):
        env = (self.app_env or "").strip().lower()
        if env == "production":
            # SQLite forbidden in production — must be PostgreSQL
            if "sqlite" in (self.database_url or "").lower():
                raise ValueError("DATABASE_URL must be PostgreSQL in production — SQLite is not safe for concurrent writes")
            # Strong secrets: placeholder rejection + >=16 in prod
            for field_name in ("jwt_secret", "internal_api_key", "postgres_password", "minio_root_password"):
                val = getattr(self, field_name, None)
                if val is not None:
                    if len(val) < 16 or any(p in val.lower() for p in PLACEHOLDERS):
                        raise ValueError(f"{field_name} must be >=16 and not placeholder in production")
            # reset_token_secret required and strong in prod
            if self.reset_token_secret is None or len(self.reset_token_secret) < 16:
                raise ValueError("RESET_TOKEN_SECRET must be >=16 and not placeholder in production")
            if any(p in self.reset_token_secret.lower() for p in PLACEHOLDERS):
                raise ValueError("RESET_TOKEN_SECRET must be >=16 and not placeholder in production")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def bootstrap_source_key_list(self) -> list[str]:
        return [item.strip() for item in self.bootstrap_source_keys.split(",") if item.strip()]

    # ── T3 helpers ──────────────────────────────────────────────────────
    #: Documented per-tier defaults (sum == legacy single-pool 6).
    TIER_CONCURRENCY_DEFAULTS: ClassVar[dict[str, int]] = {
        "strategic": 3,
        "complementary": 2,
        "experimental": 1,
    }

    def global_concurrency_cap(self) -> int:
        """Legacy total cap: min(6, SCRAPING_MAX_CONCURRENCY), at least 1."""
        return max(1, min(6, int(self.scraping_max_concurrency)))

    def tier_concurrency(self, tier: str | None) -> int:
        """Effective semaphore size for one tier (T3, reversible).

        Env override when set, else the 3/2/1 documented defaults.
        Unknown/untiered tiers share the ``experimental`` budget (lowest
        priority, still runs every tick — no starvation). Always clamped to
        ``[1, global_concurrency_cap()]`` so new defaults can never exceed
        today's prod load without an explicit opt-in.
        """
        key = (tier or "").strip().lower()
        overrides = {
            "strategic": self.scraping_max_concurrency_strategic,
            "complementary": self.scraping_max_concurrency_complementary,
            "experimental": self.scraping_max_concurrency_experimental,
        }
        raw = overrides.get(key, self.scraping_max_concurrency_experimental)
        if raw is None:
            raw = self.TIER_CONCURRENCY_DEFAULTS.get(key, self.TIER_CONCURRENCY_DEFAULTS["experimental"])
        return max(1, min(int(raw), self.global_concurrency_cap()))

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.chat_model:
        settings.chat_model = settings.llm_model
    return settings


def check_production_sqlite(app_env: str | None = None, database_url: str | None = None) -> None:
    """Log a warning when DATABASE_URL uses SQLite in a production environment.

    SQLite is not safe for concurrent production workloads â€” it can cause
    data corruption under concurrent writes. This check warns operators who
    forget to configure a real database in production.

    Call this once during application startup.
    """
    env = (app_env or get_settings().app_env).strip().lower()
    db_url = (database_url or get_settings().database_url).strip().lower()
    if env == "production" and "sqlite" in db_url:
        logger.warning(
            "DATABASE_URL uses SQLite in APP_ENV=production. "
            "SQLite is NOT safe for production â€” concurrent writes can "
            "cause data corruption. Configure PostgreSQL via DATABASE_URL "
            "in your environment."
        )


def effective_llm_provider(provider: str | None = None) -> str:
    value = (provider or get_settings().llm_provider).strip().lower()
    if value == "mock":
        raise ValueError("LLM_PROVIDER=mock is not supported")
    if value in {"local", ""}:
        return "local"
    return value






