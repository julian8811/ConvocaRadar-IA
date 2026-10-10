import asyncio
import json
from copy import deepcopy
from datetime import datetime
from urllib.parse import quote

from app.connectors.common import (
    apply_extracted_fields,
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

# ── E8 grants-gov detail XHR award gap-fill ────────────────────────────────
#
# The search2 list API returns hits WITHOUT award fields, and the detail HTML
# (SSR and rendered) is a JS shell without amounts. The real detail data comes
# from a keyless endpoint (discovered by intercepting the ficha's traffic):
#   POST apply07.grants.gov/grantsws/rest/opportunity/details
#   Content-Type: application/x-www-form-urlencoded;charset=UTF-8
#   Referer: https://www.grants.gov/
#   body: oppId={id} (form-encoded)
# → 200 JSON with awardCeiling / awardFloor / awardCeilingFormatted /
#   awardFloorFormatted / estimatedFunding / synopsisDesc.
# Candidates still missing funding get a bounded, best-effort XHR gap-fill
# mapped through the same funding extractor the search-hit parse uses.
# Gap-fill only — existing funding/dates are never overwritten.

GRANTS_GOV_DETAIL_XHR_URL = "https://apply07.grants.gov/grantsws/rest/opportunity/details"
GRANTS_GOV_DETAIL_XHR_CAP: int = 25
GRANTS_GOV_DETAIL_XHR_TIMEOUT: int = 15
GRANTS_GOV_DETAIL_XHR_CONCURRENCY: int = 5

# Priority order mirrors the search-hit parse (ceiling → estimated → floor),
# with the human-formatted "$1,234" variants as fallback for each level.
_DETAIL_FUNDING_KEYS: tuple[str, ...] = (
    "awardCeiling",
    "awardCeilingFormatted",
    "estimatedFunding",
    "awardFloor",
    "awardFloorFormatted",
    "funding",
)


def detail_funding_fields(payload: dict) -> dict[str, object]:
    """Map a detail-XHR payload onto candidate funding field names.

    Runs the first present award blob through :func:`extract_funding_details`
    (the exact mapping the search-hit parse uses). Plain numeric blobs such as
    ``"750000"`` carry no currency token for the extractor, so a bare-number
    salvage pass fills the value; a found value with no detected currency
    defaults to USD — this endpoint only serves US federal awards quoted in
    dollars (``$``-formatted). Returns ``{}`` when no award key is present.
    """
    fields: dict[str, object] = {}
    if not isinstance(payload, dict):
        return fields
    blob = next(
        (payload.get(key) for key in _DETAIL_FUNDING_KEYS if payload.get(key) not in (None, "")),
        None,
    )
    if blob is None:
        return fields
    text = str(blob).strip()
    if not text:
        return fields
    raw, value, currency = extract_funding_details(text)
    if value is None:
        # Bare numeric blob ("750000") — strip grouping/formatting and read it.
        try:
            value = float(text.replace("$", "").replace(",", "").strip())
        except ValueError:
            value = None
    if not raw:
        raw = text[:200]
    if raw:
        fields["funding_amount_raw"] = raw
    if value is not None:
        fields["funding_amount_value"] = value
        fields["funding_amount_currency"] = currency or "USD"
    return fields


async def _fetch_grants_gov_detail(opp_id: str) -> dict | None:
    """POST one detail-XHR request; return the JSON dict or None. Never raises."""
    opp_id = (opp_id or "").strip()
    if not opp_id:
        return None
    try:
        from app.core.http_client import http_client

        client = await http_client()
        response = await client.request(
            "POST",
            GRANTS_GOV_DETAIL_XHR_URL,
            content=f"oppId={quote(opp_id, safe='')}",
            headers={
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "Referer": "https://www.grants.gov/",
            },
            timeout=GRANTS_GOV_DETAIL_XHR_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _candidate_needs_detail_xhr(candidate: OpportunityCandidate) -> bool:
    """True when a grants-gov candidate still has no funding to gap-fill."""
    return (
        candidate.funding_amount_raw is None and candidate.funding_amount_value is None
    )


def _detail_opp_id(candidate: OpportunityCandidate) -> str:
    """Opportunity id for the XHR body: external_id, else the detail-URL tail."""
    if candidate.external_id and candidate.external_id.strip():
        return candidate.external_id.strip()
    return (candidate.official_url or "").rstrip("/").rsplit("/", 1)[-1]


async def enrich_grants_gov_funding_xhr(
    candidates: list[OpportunityCandidate],
) -> list[OpportunityCandidate]:
    """Gap-fill unfunded grants-gov candidates via the keyless detail XHR.

    Fetches at most GRANTS_GOV_DETAIL_XHR_CAP details (funded candidates are
    skipped, order and count are preserved) with bounded concurrency and merges
    each result with apply_extracted_fields (gap-fill only). Best-effort:
    any fetch/parse failure degrades to the input candidate, never raises.
    """
    try:
        targets = [c for c in candidates if _candidate_needs_detail_xhr(c)][
            :GRANTS_GOV_DETAIL_XHR_CAP
        ]
        if not targets:
            return list(candidates)
        semaphore = asyncio.Semaphore(GRANTS_GOV_DETAIL_XHR_CONCURRENCY)

        async def _one(candidate: OpportunityCandidate) -> dict | None:
            async with semaphore:
                payload = await _fetch_grants_gov_detail(_detail_opp_id(candidate))
            if not payload:
                return None
            try:
                fields = detail_funding_fields(payload)
            except Exception:
                return None
            return fields or None

        results = await asyncio.gather(
            *(_one(candidate) for candidate in targets),
            return_exceptions=True,
        )
        url_to_fields: dict[str, dict] = {}
        for candidate, result in zip(targets, results):
            if isinstance(result, dict) and result:
                url_to_fields.setdefault(candidate.official_url, result)
        enriched: list[OpportunityCandidate] = []
        for candidate in candidates:
            fields = url_to_fields.get(candidate.official_url)
            if fields is not None:
                enriched.append(apply_extracted_fields(candidate, fields))
            else:
                enriched.append(deepcopy(candidate))
        return enriched
    except Exception:
        return list(candidates)


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
