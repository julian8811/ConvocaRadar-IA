import json
from datetime import datetime

from worker.connectors.common import fetch_httpx_text
from worker.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from worker.connectors.simpler_grants import SimplerGrantsConnector


GRANTS_GOV_SEARCH_URL = "https://api.grants.gov/v1/api/search2"
GRANTS_GOV_SEARCH_PAGE = "https://www.grants.gov/search-grants"
GRANTS_GOV_OPPORTUNITY_URL = "https://www.grants.gov/search-results-detail/{opportunity_id}"


def _parse_grants_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


class GrantsGovConnector:
    source_key = "grants-gov"

    def __init__(self, base_url: str | None = None, keyword: str = "") -> None:
        self.base_url = base_url or GRANTS_GOV_SEARCH_URL
        self.keyword = keyword

    async def fetch(self) -> RawSourceResult:
        payload = {
            "rows": 25,
            "keyword": self.keyword,
            "oppStatuses": "forecasted|posted",
            "sortBy": "openDate|desc",
        }
        try:
            final_url, content, content_type = await fetch_httpx_text(
                self.base_url,
                method="POST",
                payload=payload,
                fallback_content_type="application/json",
            )
        except Exception:
            final_url, content, content_type = await fetch_httpx_text(GRANTS_GOV_SEARCH_PAGE, fallback_content_type="text/html")
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=content,
            content_type=content_type,
            metadata={"request": payload},
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        if not raw.content.lstrip().startswith("{"):
            return await SimplerGrantsConnector(GRANTS_GOV_SEARCH_PAGE).parse(raw)
        payload = json.loads(raw.content)
        data = payload.get("data") or {}
        hits = data.get("oppHits") or []
        if not hits:
            fallback = await SimplerGrantsConnector(GRANTS_GOV_SEARCH_PAGE).fetch()
            return await SimplerGrantsConnector(GRANTS_GOV_SEARCH_PAGE).parse(fallback)
        candidates: list[OpportunityCandidate] = []
        for hit in hits:
            opportunity_id = str(hit.get("id") or "").strip()
            title = str(hit.get("title") or "").strip()
            agency = str(hit.get("agencyName") or hit.get("agencyCode") or "Grants.gov").strip()
            if not opportunity_id or not title:
                continue
            number = str(hit.get("number") or "").strip()
            status = str(hit.get("oppStatus") or "").strip()
            alns = ", ".join(hit.get("alnist") or [])
            summary_parts = [part for part in [number, agency, f"Status: {status}" if status else "", f"ALN: {alns}" if alns else ""] if part]
            candidates.append(
                OpportunityCandidate(
                    title=title[:180],
                    entity=agency,
                    country="United States",
                    official_url=GRANTS_GOV_OPPORTUNITY_URL.format(opportunity_id=opportunity_id),
                    summary=" | ".join(summary_parts),
                    categories=["grants", "federal funding"],
                    topics=[status] if status else [],
                    raw_text=json.dumps(hit, ensure_ascii=False),
                    confidence_score=0.82,
                    open_date=_parse_grants_date(hit.get("openDate")),
                    close_date=_parse_grants_date(hit.get("closeDate")),
                )
            )
        return candidates

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title:
            return ValidationResult(ok=False, reason="Missing title")
        if not candidate.official_url.startswith(("https://www.grants.gov/", "https://simpler.grants.gov/")):
            return ValidationResult(ok=False, reason="Unexpected official URL")
        return ValidationResult(ok=True)
