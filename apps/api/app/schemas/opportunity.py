"""Opportunity-related Pydantic schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


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
