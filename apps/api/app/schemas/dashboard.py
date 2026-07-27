"""Dashboard-related Pydantic schemas (triage, pipeline, health)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.source import SourceHealthRead


class DashboardBreakdownItem(BaseModel):
    name: str
    total: int


class DashboardOpportunityItem(BaseModel):
    id: str
    title: str
    entity: str
    country: str
    status: str
    close_date: datetime | None = None
    funding_amount_raw: str | None = None
    funding_amount_value: float | None = None
    funding_amount_currency: str | None = None
    score: float | None = None
    priority: str | None = None
    days_to_close: int | None = None


class DashboardSourceAlert(BaseModel):
    source_id: str
    name: str
    status: Literal["degraded", "failing"]


class DashboardDataCoverage(BaseModel):
    with_summary: int
    with_amount: int
    with_close_date: int
    with_source: int
    embeddings_coverage: float | None = None


class DashboardProfileSummary(BaseModel):
    completeness: float
    missing_fields: list[str]


class DashboardSummaryRead(BaseModel):
    total_opportunities: int
    open_opportunities: int
    closing_soon_opportunities: int
    high_match_opportunities: int
    top_scored: list[DashboardOpportunityItem]
    closing_soon: list[DashboardOpportunityItem]
    status_breakdown: list[DashboardBreakdownItem]
    country_breakdown: list[DashboardBreakdownItem]
    degraded_sources: int
    failing_sources: int
    source_alerts: list[DashboardSourceAlert]
    data_coverage: DashboardDataCoverage
    profile: DashboardProfileSummary


class AdminMetricsRead(BaseModel):
    active_sources: int
    total_sources: int
    degraded_sources: int
    failing_sources: int
    stale_sources: int = 0
    opportunities: int
    open_opportunities: int
    closing_soon_opportunities: int
    embeddings_total: int = 0
    embeddings_missing: int = 0
    embeddings_coverage: float = 0.0
    failed_source_runs: int
    failed_tasks: int
    reports: int
    pending_alerts: int
    source_health_alerts: int
    sent_alerts: int
    audit_events: int


# ── Triage ──


class TriageOpportunityItem(BaseModel):
    id: str
    title: str
    country: str | None = None
    currency: str | None = None
    funding_amount: float | None = None
    days_to_close: int | None = None
    score: float | None = None
    source_key: str | None = None


class TriageRead(BaseModel):
    review_queue: list[TriageOpportunityItem]
    closing_soon_7d: list[TriageOpportunityItem]


# ── Pipeline ──


class PipelineOpportunityItem(BaseModel):
    id: str
    title: str
    country: str | None = None
    currency: str | None = None
    funding_amount: float | None = None
    days_to_close: int | None = None
    score: float | None = None
    reasons: list[str] = Field(default_factory=list)
    source_key: str | None = None


class PipelineRead(BaseModel):
    top_scored: list[PipelineOpportunityItem]
    closing_soon: list[PipelineOpportunityItem]


# ── Health ──


class HealthKpis(BaseModel):
    total: int
    open: int
    closing_soon: int
    high_match: int


class HealthRead(BaseModel):
    kpis: HealthKpis
    status_breakdown: list[DashboardBreakdownItem]
    country_breakdown: list[DashboardBreakdownItem]
    data_coverage: DashboardDataCoverage
    sources_health: list[SourceHealthRead]
    failing_sources: int
    degraded_sources: int
    source_alerts: list[DashboardSourceAlert]
    score_distribution: list[DashboardBreakdownItem] = []
    funding_ranges: list[DashboardBreakdownItem] = []
    source_contribution: list[DashboardBreakdownItem] = []
    opportunities_timeline: list[DashboardBreakdownItem] = []
    category_distribution: list[DashboardBreakdownItem] = []
