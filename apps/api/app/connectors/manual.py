from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult


class ManualConnector:
    def __init__(self, source_key: str, base_url: str) -> None:
        self.source_key = source_key
        self.base_url = base_url

    async def fetch(self) -> RawSourceResult:
        return RawSourceResult(
            source_key=self.source_key,
            url=self.base_url,
            content="",
            content_type="text/plain",
            metadata={"mode": "manual"},
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        return []

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        return ValidationResult(ok=False, reason="Manual sources are curated outside automated scraping")
