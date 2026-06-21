from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    redis_url: str = "redis://localhost:6379/0"
    database_url: str = "sqlite:///../../apps/api/convocaradar.db"
    scraping_user_agent: str = "ConvocaRadarBot/0.1"
    scraping_timeout_seconds: int = 30
    backend_url: str = "http://localhost:8000"
    internal_api_key: str = "change_me_internal"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> WorkerSettings:
    return WorkerSettings()
