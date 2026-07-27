"""Source-related Pydantic schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


class SourceBase(BaseModel):
    name: str
    key: str
    base_url: HttpUrl | str
    country: str = "Colombia"
    region: str = "LatAm"
    source_type: str = "html"
    category: list[str] = Field(default_factory=list)
    enabled: bool = True
    scraping_frequency: str = "daily"
    allowed_domains: list[str] = Field(default_factory=list)


class SourceCreate(SourceBase):
    pass


class SourceUpdate(BaseModel):
    name: str | None = None
    base_url: HttpUrl | str | None = None
    country: str | None = None
    region: str | None = None
    source_type: str | None = None
    category: list[str] | None = None
    enabled: bool | None = None
    scraping_frequency: str | None = None
    allowed_domains: list[str] | None = None


class SourceRead(SourceBase):
    id: str
    organization_id: str | None
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SourceHealthRead(BaseModel):
    source_id: str
    key: str
    name: str
    source_type: str
    status: Literal["healthy", "degraded", "failing", "idle"]
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    recent_runs: int
    recent_failures: int
    recent_items_found: int
    recent_items_created: int
    recent_items_updated: int
    success_rate: float = 0.0
    failure_rate: float = 0.0
    average_items_found: float = 0.0
    last_run_duration_seconds: float | None = None
    days_since_last_success: int | None = None
    last_run_status: str | None = None
    health_score: int = 0
    health_status: str = "unknown"
    tier: str | None = None
    auto_paused: bool = False
    failure_category: str | None = None


class SourceRunRead(BaseModel):
    id: str
    source_id: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    items_found: int
    items_created: int
    items_updated: int
    items_failed: int
    error_message: str | None = None
    logs: list[dict[str, Any]]
    progress: dict[str, str] | None = None

    model_config = {"from_attributes": True}


class SourceRunOverviewRead(SourceRunRead):
    source_key: str
    source_name: str


class SourceRunCandidate(BaseModel):
    title: str
    entity: str
    country: str = "Por validar"
    official_url: str | None = None
    summary: str = ""
    categories: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    raw_text: str = ""
    confidence_score: float = 0.5
    open_date: datetime | None = None
    close_date: datetime | None = None
    funding_amount_raw: str | None = None


class SourceRunComplete(BaseModel):
    task_id: str | None = None
    status: Literal["success", "failed"] = "success"
    items_found: int = 0
    items_valid: int = 0
    items_invalid: int = 0
    items: list[SourceRunCandidate] = Field(default_factory=list)
    error_message: str | None = None
    logs: list[dict[str, Any]] = Field(default_factory=list)


class ConnectorProbeRequest(BaseModel):
    source_key: str
    base_url: str | None = None
    source_type: str | None = None
