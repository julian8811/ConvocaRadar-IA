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
    title: str
    entity: str
    country: str
    official_url: str
    language: str = "auto"
    summary: str = ""
    categories: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)
    raw_text: str = ""
    confidence_score: float = 0.5
    open_date: datetime | None = None
    close_date: datetime | None = None
    funding_amount_raw: str | None = None


@dataclass
class ValidationResult:
    ok: bool
    reason: str = ""


class SourceConnector(Protocol):
    source_key: str

    async def fetch(self) -> RawSourceResult:
        ...

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        ...

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        ...
