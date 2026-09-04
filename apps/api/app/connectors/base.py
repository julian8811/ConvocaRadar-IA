from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass
class RawSourceResult:
    source_key: str
    url: str
    content: str
    content_type: str = "text/html"
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class OpportunityCandidate:
    """What a connector extracted for a single opportunity.

    This mirrors the writable columns of ``Opportunity`` so a connector can
    express everything it manages to scrape. Any field missing here is a field
    the pipeline cannot persist no matter how well a connector extracts it.
    """

    title: str
    entity: str
    country: str
    official_url: str
    language: str = "auto"
    summary: str = ""
    description: str = ""
    categories: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    eligible_applicants: list[str] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)
    documents_required: list[str] = field(default_factory=list)
    evaluation_criteria: list[str] = field(default_factory=list)
    restrictions: list[str] = field(default_factory=list)
    raw_text: str = ""
    confidence_score: float = 0.5
    open_date: datetime | None = None
    close_date: datetime | None = None
    funding_amount_raw: str | None = None
    funding_amount_value: float | None = None
    funding_amount_currency: str | None = None
    application_url: str | None = None
    region: str | None = None
    external_id: str | None = None
    # Ephemeral candidate-scoped HTML for runner fill — never list-page raw.content.
    snippet_html: str | None = None


@dataclass
class ValidationResult:
    ok: bool
    reason: str = ""


class SourceConnector(Protocol):
    source_key: str

    async def fetch(self) -> RawSourceResult: ...

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]: ...

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult: ...
