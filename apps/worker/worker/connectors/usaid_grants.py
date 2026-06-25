from __future__ import annotations

import json

from worker.connectors.grants_gov import GrantsGovConnector, GRANTS_GOV_SEARCH_URL
from worker.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult


class UsaidGrantsConnector(GrantsGovConnector):
    source_key = "usaid-grants"

    def __init__(self, base_url: str | None = None) -> None:
        super().__init__(base_url or GRANTS_GOV_SEARCH_URL, keyword="USAID")

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        candidates = await super().parse(raw)
        for candidate in candidates:
            lowered = f"{candidate.title} {candidate.summary}".lower()
            if "usaid" in lowered:
                candidate.entity = "USAID"
            candidate.country = candidate.country or "United States"
            candidate.categories = ["grants", "cooperation", "international development"]
            candidate.topics = list(dict.fromkeys([*(candidate.topics or []), "USAID"]))
        return candidates[:50]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        return ValidationResult(ok=bool(candidate.title and candidate.official_url))
