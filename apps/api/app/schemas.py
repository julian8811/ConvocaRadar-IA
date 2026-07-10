from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, HttpUrl


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserRead(BaseModel):
    id: str
    email: EmailStr
    name: str
    role: str
    organization_id: str | None

    model_config = {"from_attributes": True}


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10)
    name: str
    organization_name: str
    organization_type: str = "other"
    country: str = "Colombia"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# PR2 (account recovery): three new request bodies for the password
# management endpoints. All three are intentionally simple — the route
# handlers do the database / JWT work; the schemas only validate the
# shape and the project-standard password length (10 chars, matching
# ``RegisterRequest.password``).


class ChangePasswordRequest(BaseModel):
    """Body for ``POST /api/v1/auth/change-password`` (authenticated).

    The current password is checked against ``User.password_hash`` by the
    route handler; the new password is then hashed and stored. The 10-char
    minimum matches the registration rule.
    """

    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=10, max_length=128)


class ForgotPasswordRequest(BaseModel):
    """Body for ``POST /api/v1/auth/forgot-password`` (public, rate-limited)."""

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Body for ``POST /api/v1/auth/reset-password`` (public, JWT-protected)."""

    token: str = Field(min_length=1)
    new_password: str = Field(min_length=10, max_length=128)


class OrganizationRead(BaseModel):
    id: str
    name: str
    slug: str
    type: str
    country: str
    website: str | None = None

    model_config = {"from_attributes": True}


class OrganizationUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    country: str | None = None
    website: str | None = None


class OrganizationProfileUpsert(BaseModel):
    description: str = ""
    country: str = "Colombia"
    regions_of_interest: list[str] = Field(default_factory=list)
    organization_type: str = "other"
    areas_of_interest: list[str] = Field(default_factory=list)
    funding_types: list[str] = Field(default_factory=list)
    min_funding_amount: float | None = None
    max_funding_amount: float | None = None
    preferred_currencies: list[str] = Field(default_factory=list)
    eligible_international: bool = True
    languages: list[str] = Field(default_factory=lambda: ["es"])
    has_research_groups: bool = False
    has_company_partners: bool = False
    has_university_partners: bool = False
    application_capacity: Literal["low", "medium", "high"] = "medium"


class OrganizationProfileRead(OrganizationProfileUpsert):
    id: str
    organization_id: str

    model_config = {"from_attributes": True}


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
    # Change C: health score & quality gate
    health_score: int = 0
    health_status: str = "unknown"  # healthy/stable/degraded/critical
    tier: str | None = None
    auto_paused: bool = False


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
    # PR2: per-phase progress tracking (fetch/parse/persist ISO timestamps)
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


class TaskRead(BaseModel):
    id: str
    organization_id: str | None
    source_run_id: str | None
    task_type: str
    provider: str
    status: str
    external_id: str | None = None
    payload: dict[str, Any]
    result: dict[str, Any]
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class OpportunityCreate(BaseModel):
    source_id: str | None = None
    external_id: str | None = None
    title: str
    entity: str
    country: str = "Colombia"
    region: str | None = None
    categories: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    description: str = ""
    summary: str = ""
    raw_text: str = ""
    official_url: str | None = None
    application_url: str | None = None
    open_date: datetime | None = None
    close_date: datetime | None = None
    funding_amount_value: float | None = None
    funding_amount_currency: str | None = None
    funding_amount_raw: str | None = None
    eligible_applicants: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    documents_required: list[str] = Field(default_factory=list)
    evaluation_criteria: list[str] = Field(default_factory=list)
    restrictions: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    language: str = "auto"
    confidence_score: float = 0.5


class OpportunityUpdate(BaseModel):
    user_status: str | None = None
    is_favorite: bool | None = None
    summary: str | None = None
    requirements: list[str] | None = None
    risk_flags: list[str] | None = None


class OpportunityRead(OpportunityCreate):
    id: str
    organization_id: str | None
    slug: str
    status: str
    user_status: str
    is_favorite: bool
    first_seen_at: datetime
    last_seen_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class OpportunityList(BaseModel):
    items: list[OpportunityRead]
    total: int
    page: int
    page_size: int


class OpportunitySemanticMatch(BaseModel):
    opportunity: OpportunityRead
    similarity: float


class OpportunitySemanticList(BaseModel):
    query: str
    items: list[OpportunitySemanticMatch]


class OpportunityDocumentRead(BaseModel):
    id: str
    opportunity_id: str
    file_name: str
    file_type: str
    file_url: str | None = None
    storage_path: str | None = None
    checksum: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ScoreRead(BaseModel):
    id: str
    opportunity_id: str
    organization_id: str
    score: float
    priority: str
    reasons: list[str]
    warnings: list[str]
    calculated_at: datetime

    model_config = {"from_attributes": True}


class ReportCreate(BaseModel):
    title: str = "Reporte ejecutivo de convocatorias"
    report_type: str = "custom"
    format: Literal["html", "pdf", "xlsx", "csv"] = "html"
    filters: dict[str, Any] = Field(default_factory=dict)


class ReportRead(BaseModel):
    id: str
    organization_id: str
    title: str
    report_type: str
    format: str
    status: str
    html_content: str
    file_path: str | None
    filters: dict[str, Any]
    generated_at: datetime

    model_config = {"from_attributes": True}


class AlertCreate(BaseModel):
    opportunity_id: str | None = None
    alert_type: str
    channel: str = "email"
    recipient: EmailStr
    subject: str
    message: str
    scheduled_at: datetime | None = None


class AlertUpdate(BaseModel):
    status: Literal["pending", "paused", "sent", "failed"] | None = None
    recipient: EmailStr | None = None
    subject: str | None = None
    message: str | None = None
    scheduled_at: datetime | None = None


class AlertTestRequest(BaseModel):
    recipient: EmailStr


class AlertRead(AlertCreate):
    id: str
    organization_id: str
    status: str
    sent_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogRead(BaseModel):
    id: str
    organization_id: str | None
    user_id: str | None
    action: str
    resource_type: str
    resource_id: str | None
    metadata_json: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


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


# PR B-1a: Triage zone. A short, action-oriented list for the consultor
# persona that surfaces the two highest-leverage things to do today:
# the review queue (items the user previously marked for review) and
# the closing-soon-in-7-days list (any opportunity, regardless of user
# status, that closes within a week).
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


# PR B-1b: Pipeline zone. A focused payload for the lists lane: top-scored
# opportunities (with their score and the reasons that explain it) and
# closing-soon opportunities (with a numeric days_to_close countdown).
# Distinct from the existing TriageRead (which surfaces the user's review
# queue and the 7-day-closing window) so each zone can evolve independently.
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


# PR B-1c: Health zone. A focused payload for the health lane: the same
# KPI counts the legacy summary returned, plus status/country breakdowns,
# the data-coverage strip (with the now-nullable embeddings_coverage),
# and the per-source health entries. This is the new canonical source of
# truth for the Health zone; the legacy /dashboard/summary is converted
# into a thin alias that merges Triage + Pipeline + Health.
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
    # Analytics charts (new — PR analytics-dashboard)
    score_distribution: list[DashboardBreakdownItem] = []
    funding_ranges: list[DashboardBreakdownItem] = []
    source_contribution: list[DashboardBreakdownItem] = []
    opportunities_timeline: list[DashboardBreakdownItem] = []
    category_distribution: list[DashboardBreakdownItem] = []


class AiOpportunityExtract(BaseModel):
    title: str
    entity: str
    country: str
    category: list[str]
    status: str
    close_date: str | None = None
    requirements: list[str]
    documents_required: list[str]
    summary: str
    risks: list[str]
    recommendation: str
    confidence: float
    matched_keywords: list[str] = Field(default_factory=list)
    risk_level: str = "medium"
    priority: str = "medium"
    funding_amount_raw: str | None = None
    extraction_notes: list[str] = Field(default_factory=list)
    model_version: str = "local-heuristic-v2"
    provider: str = "local"
    prompt_version: str = "structured-extraction-v3"
    extraction_strategy: str = "local-heuristic"


class AiTextRequest(BaseModel):
    text: str = Field(min_length=1)
