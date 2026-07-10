from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, TypeDecorator

try:
    from pgvector.sqlalchemy import Vector
except ImportError:  # pragma: no cover - optional dependency
    Vector = None

from app.db.session import Base


PGVECTOR_AVAILABLE = Vector is not None


class EmbeddingVector(TypeDecorator[list[float]]):
    cache_ok = True
    impl = JSON

    def __init__(self, dimensions: int = 64) -> None:
        super().__init__()
        self.dimensions = dimensions

    def load_dialect_impl(self, dialect):
        if PGVECTOR_AVAILABLE and dialect.name == "postgresql":
            return dialect.type_descriptor(Vector(self.dimensions))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if value is None:
            return []
        return [float(item) for item in value]

    def process_result_value(self, value, dialect):
        if value is None:
            return []
        return [float(item) for item in value]


def uuid() -> str:
    return str(uuid4())


class OrganizationType(StrEnum):
    university = "university"
    research_group = "research_group"
    startup = "startup"
    company = "company"
    consulting_firm = "consulting_firm"
    government = "government"
    ngo = "ngo"
    other = "other"


class SourceType(StrEnum):
    api = "api"
    html = "html"
    pdf = "pdf"
    rss = "rss"
    manual = "manual"
    hybrid = "hybrid"


class OpportunityStatus(StrEnum):
    open = "open"
    closed = "closed"
    closing_soon = "closing_soon"
    unknown = "unknown"
    draft = "draft"
    archived = "archived"


class Priority(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"
    not_recommended = "not_recommended"


class Role(StrEnum):
    admin = "admin"
    member = "member"
    viewer = "viewer"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    password_hash: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, default=Role.member.value)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # PR1-1 (Alembic migration 0003) added this column. PR2-3 writes to it on
    # every successful password change / reset so the JWT claim check in
    # ``get_current_user`` can invalidate in-flight tokens. Nullable so
    # pre-migration rows (and brand-new users before their first change) are
    # valid; the route handler treats ``None`` as epoch 0 for comparison.
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    organization: Mapped["Organization | None"] = relationship(back_populates="users")


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid)
    name: Mapped[str] = mapped_column(String, index=True)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True)
    type: Mapped[str] = mapped_column(String, default=OrganizationType.other.value)
    country: Mapped[str] = mapped_column(String, default="Colombia")
    website: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    users: Mapped[list[User]] = relationship(back_populates="organization")
    profile: Mapped["OrganizationProfile | None"] = relationship(back_populates="organization")


class OrganizationProfile(Base):
    __tablename__ = "organization_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    country: Mapped[str] = mapped_column(String, default="Colombia")
    regions_of_interest: Mapped[list[str]] = mapped_column(JSON, default=list)
    organization_type: Mapped[str] = mapped_column(String, default=OrganizationType.other.value)
    areas_of_interest: Mapped[list[str]] = mapped_column(JSON, default=list)
    funding_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    min_funding_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_funding_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    preferred_currencies: Mapped[list[str]] = mapped_column(JSON, default=list)
    eligible_international: Mapped[bool] = mapped_column(Boolean, default=True)
    languages: Mapped[list[str]] = mapped_column(JSON, default=list)
    has_research_groups: Mapped[bool] = mapped_column(Boolean, default=False)
    has_company_partners: Mapped[bool] = mapped_column(Boolean, default=False)
    has_university_partners: Mapped[bool] = mapped_column(Boolean, default=False)
    application_capacity: Mapped[str] = mapped_column(String, default="medium")

    organization: Mapped[Organization] = relationship(back_populates="profile")


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    name: Mapped[str] = mapped_column(String, index=True)
    key: Mapped[str] = mapped_column(String, index=True)
    base_url: Mapped[str] = mapped_column(String)
    country: Mapped[str] = mapped_column(String, default="Colombia")
    region: Mapped[str] = mapped_column(String, default="LatAm")
    source_type: Mapped[str] = mapped_column(String, default=SourceType.html.value)
    category: Mapped[list[str]] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    scraping_frequency: Mapped[str] = mapped_column(String, default="daily")
    allowed_domains: Mapped[list[str]] = mapped_column(JSON, default=list)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Change C: health score & quality gate fields
    tier: Mapped[str | None] = mapped_column(String, nullable=True)  # "strategic", "complementary", "experimental"
    auto_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    consecutive_empty_runs: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class SourceRun(Base):
    __tablename__ = "source_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    items_found: Mapped[int] = mapped_column(Integer, default=0)
    items_created: Mapped[int] = mapped_column(Integer, default=0)
    items_updated: Mapped[int] = mapped_column(Integer, default=0)
    items_failed: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    logs: Mapped[list[dict]] = mapped_column(JSON, default=list)
    # PR2: progress tracking — updated by runner after fetch/parse/persist steps
    progress: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    source_run_id: Mapped[str | None] = mapped_column(ForeignKey("source_runs.id"), nullable=True, index=True)
    task_type: Mapped[str] = mapped_column(String, index=True)
    provider: Mapped[str] = mapped_column(String, default="local")
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    external_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(String, index=True)
    slug: Mapped[str] = mapped_column(String, index=True)
    entity: Mapped[str] = mapped_column(String, index=True)
    country: Mapped[str] = mapped_column(String, index=True)
    region: Mapped[str | None] = mapped_column(String, nullable=True)
    categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    topics: Mapped[list[str]] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    raw_text: Mapped[str] = mapped_column(Text, default="")
    official_url: Mapped[str | None] = mapped_column(String, nullable=True)
    application_url: Mapped[str | None] = mapped_column(String, nullable=True)
    open_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    close_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String, default=OpportunityStatus.unknown.value, index=True)
    funding_amount_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    funding_amount_currency: Mapped[str | None] = mapped_column(String, nullable=True)
    funding_amount_raw: Mapped[str | None] = mapped_column(String, nullable=True)
    eligible_applicants: Mapped[list[str]] = mapped_column(JSON, default=list)
    requirements: Mapped[list[str]] = mapped_column(JSON, default=list)
    documents_required: Mapped[list[str]] = mapped_column(JSON, default=list)
    evaluation_criteria: Mapped[list[str]] = mapped_column(JSON, default=list)
    restrictions: Mapped[list[str]] = mapped_column(JSON, default=list)
    risk_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    language: Mapped[str] = mapped_column(String, default="es")
    confidence_score: Mapped[float] = mapped_column(Float, default=0.5)
    user_status: Mapped[str] = mapped_column(String, default="review")
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class OpportunityDocument(Base):
    __tablename__ = "opportunity_documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), index=True)
    file_name: Mapped[str] = mapped_column(String)
    file_type: Mapped[str] = mapped_column(String)
    file_url: Mapped[str | None] = mapped_column(String, nullable=True)
    storage_path: Mapped[str | None] = mapped_column(String, nullable=True)
    text_content: Mapped[str] = mapped_column(Text, default="")
    checksum: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class OpportunityScore(Base):
    __tablename__ = "opportunity_scores"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    score: Mapped[float] = mapped_column(Float)
    priority: Mapped[str] = mapped_column(String)
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class OpportunityEmbedding(Base):
    __tablename__ = "opportunity_embeddings"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), unique=True, index=True)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    model_version: Mapped[str] = mapped_column(String, default="local-hash-embeddings-v2")
    source_text: Mapped[str] = mapped_column(Text, default="")
    embedding: Mapped[list[float]] = mapped_column(EmbeddingVector(64), default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    title: Mapped[str] = mapped_column(String)
    report_type: Mapped[str] = mapped_column(String, default="custom")
    format: Mapped[str] = mapped_column(String, default="html")
    status: Mapped[str] = mapped_column(String, default="ready")
    html_content: Mapped[str] = mapped_column(Text, default="")
    file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    generated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    opportunity_id: Mapped[str | None] = mapped_column(ForeignKey("opportunities.id"), nullable=True)
    alert_type: Mapped[str] = mapped_column(String)
    channel: Mapped[str] = mapped_column(String, default="email")
    recipient: Mapped[str] = mapped_column(String)
    subject: Mapped[str] = mapped_column(String)
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="pending")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uuid)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String)
    resource_type: Mapped[str] = mapped_column(String)
    resource_id: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


Index("ix_opportunity_filters", Opportunity.country, Opportunity.status, Opportunity.close_date)
if PGVECTOR_AVAILABLE:
    Index(
        "ix_opportunity_embeddings_vector",
        OpportunityEmbedding.embedding,
        postgresql_using="ivfflat",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
