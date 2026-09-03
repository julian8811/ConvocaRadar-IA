import json
from datetime import datetime

from app.connectors.common import (
    extract_funding_details,
    fetch_httpx_text,
    fill_candidate_from_content,
    is_shell_response,
    maybe_retry_shell_with_pw,
)
from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.registry import register
from app.connectors.simpler_grants import SimplerGrantsConnector


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


@register("grants-gov")
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
            # Use short timeout for the API POST — if it's slow, fail fast
            # and fall back to the HTML search page.
            final_url, content, content_type = await fetch_httpx_text(
                self.base_url,
                method="POST",
                payload=payload,
                fallback_content_type="application/json",
                timeout_seconds=30,
            )
        except Exception:
            final_url, content, content_type = await fetch_httpx_text(
                GRANTS_GOV_SEARCH_PAGE, fallback_content_type="text/html"
            )
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=content,
            content_type=content_type,
            metadata={"request": payload},
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        # SPA shell retry (023 S3): if 200 text/html thin shell with 0 cands and allowlisted, 1× PW retry
        if raw.content_type.startswith("text/html") and is_shell_response(raw.content, raw.content_type, 0):
            retried = await maybe_retry_shell_with_pw(
                content=raw.content,
                content_type=raw.content_type,
                candidates=0,
                source_key=self.source_key,
                url=raw.url,
            )
            if retried is not None:
                raw = RawSourceResult(
                    source_key=raw.source_key,
                    url=retried[0],
                    content=retried[1],
                    content_type=retried[2],
                    metadata=raw.metadata,
                )
        if not raw.content.lstrip().startswith("{"):
            # Simpler fallback may also be shell; delegate its own retry
            cands = await SimplerGrantsConnector(GRANTS_GOV_SEARCH_PAGE).parse(raw)
            if not cands and is_shell_response(raw.content, raw.content_type, 0):
                retried = await maybe_retry_shell_with_pw(
                    content=raw.content,
                    content_type=raw.content_type,
                    candidates=0,
                    source_key=self.source_key,
                    url=raw.url,
                )
                if retried is not None:
                    raw2 = RawSourceResult(
                        source_key=raw.source_key,
                        url=retried[0],
                        content=retried[1],
                        content_type=retried[2],
                        metadata=raw.metadata,
                    )
                    return await SimplerGrantsConnector(GRANTS_GOV_SEARCH_PAGE).parse(raw2)
            return cands
        try:
            payload = json.loads(raw.content)
        except json.JSONDecodeError:
            return []
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
            synopsis = str(
                hit.get("synopsis") or hit.get("description") or hit.get("summary") or ""
            ).strip()
            summary = synopsis or title
            funding_blob = (
                hit.get("awardCeiling")
                or hit.get("estimatedFunding")
                or hit.get("awardFloor")
                or hit.get("funding")
            )
            funding_raw, funding_value, funding_currency = (None, None, None)
            if funding_blob not in (None, ""):
                funding_raw, funding_value, funding_currency = extract_funding_details(
                    str(funding_blob)
                )
                if not funding_raw:
                    funding_raw = str(funding_blob).strip()[:200]
            candidate = OpportunityCandidate(
                title=title[:180],
                entity=agency,
                country="United States",
                official_url=GRANTS_GOV_OPPORTUNITY_URL.format(opportunity_id=opportunity_id),
                summary=summary[:700],
                description=synopsis[:4000] if synopsis else "",
                categories=["grants", "federal funding"],
                topics=[status] if status else [],
                raw_text=json.dumps(hit, ensure_ascii=False),
                confidence_score=0.82,
                open_date=_parse_grants_date(hit.get("openDate")),
                close_date=_parse_grants_date(hit.get("closeDate")),
                funding_amount_raw=funding_raw,
                funding_amount_value=funding_value,
                funding_amount_currency=funding_currency,
                external_id=opportunity_id or number or None,
            )
            candidates.append(
                fill_candidate_from_content(
                    candidate,
                    text=" ".join(part for part in [synopsis, number, agency, status, alns] if part),
                    page_url=candidate.official_url,
                )
            )
        return candidates

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title:
            return ValidationResult(ok=False, reason="Missing title")
        if not candidate.official_url.startswith(
            ("https://www.grants.gov/", "https://simpler.grants.gov/")
        ):
            return ValidationResult(ok=False, reason="Unexpected official URL")
        return ValidationResult(ok=True)
