from __future__ import annotations

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import fetch_httpx_text
from app.connectors.rss import RssConnector
from app.connectors.simpler_grants import SimplerGrantsConnector


GRANTS_GOV_RSS_URL = "https://www.grants.gov/rss/GG_OppModByCategory.xml"
GRANTS_GOV_FORECAST_URL = "https://www.grants.gov/rss/GG_ForecastOpportunities.xml"
GRANTS_GOV_SEARCH_PAGE = "https://simpler.grants.gov/search"


class GrantsGovRssConnector:
    def __init__(self, source_key: str = "grants-gov-rss", base_url: str | None = None) -> None:
        self.source_key = source_key
        self.base_url = base_url or GRANTS_GOV_RSS_URL

    async def fetch(self) -> RawSourceResult:
        final_url, content, content_type = await fetch_httpx_text(
            self.base_url,
            fallback_content_type="application/rss+xml",
        )
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=content,
            content_type=content_type,
        )

    async def _fallback_search(self) -> RawSourceResult:
        return await SimplerGrantsConnector(GRANTS_GOV_SEARCH_PAGE).fetch()

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        normalized = raw.content.lstrip()
        upper = raw.content.upper()
        if "PAGE NOT FOUND" in upper or "SEARCH FUNDING OPPORTUNITIES" in upper:
            fallback = await self._fallback_search()
            return await SimplerGrantsConnector(GRANTS_GOV_SEARCH_PAGE).parse(fallback)
        if normalized.startswith("<"):
            try:
                return await RssConnector(self.source_key, self.base_url).parse(raw)
            except Exception:
                fallback = await self._fallback_search()
                return await SimplerGrantsConnector(GRANTS_GOV_SEARCH_PAGE).parse(fallback)
        fallback = await self._fallback_search()
        return await SimplerGrantsConnector(GRANTS_GOV_SEARCH_PAGE).parse(fallback)

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or URL")
        if not candidate.official_url.startswith(("https://www.grants.gov/", "https://simpler.grants.gov/")):
            return ValidationResult(ok=False, reason="Unexpected official URL")
        return ValidationResult(ok=True)
