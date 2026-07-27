"""Organization and profile Pydantic schemas."""

from typing import Literal

from pydantic import BaseModel, Field


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
