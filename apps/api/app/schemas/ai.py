"""AI extraction Pydantic schemas."""

from pydantic import BaseModel, Field


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
