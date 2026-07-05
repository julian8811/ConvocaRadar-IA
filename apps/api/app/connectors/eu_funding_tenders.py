import json
import re
from datetime import UTC, datetime
from urllib.parse import quote_plus

from app.core.config import get_settings
from app.connectors.common import fetch_httpx_text
from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult


EU_PORTAL_URL = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/calls-for-proposals"
EU_TOPIC_URL = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/{identifier}"
EU_SEARCH_URL_TEMPLATE = "https://api.tech.ec.europa.eu/search-api/prod/rest/search?apiKey={api_key}&text={term}&pageSize=50&pageNumber=1"
EU_TERMS = ["2026", "open", "call", "funding", "research and innovation"]


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _first_text(value: object) -> str | None:
    if isinstance(value, list) and value:
        first = value[0]
        return str(first).strip() if first is not None else None
    if isinstance(value, str):
        return value.strip()
    return None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%d %B %Y"):
        try:
            parsed = datetime.strptime(value.replace("Z", "+0000"), fmt)
        except ValueError:
            continue
        return parsed.astimezone(UTC).replace(tzinfo=None)
    return None


def _parse_action_dates(actions: list[object]) -> tuple[datetime | None, datetime | None]:
    open_date = None
    close_date = None
    for action in actions:
        if isinstance(action, str):
            try:
                parsed = json.loads(action)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, list) and parsed:
                action = parsed[0]
        if not isinstance(action, dict):
            continue
        planned = action.get("plannedOpeningDate")
        deadlines = action.get("deadlineDates") or []
        if planned and not open_date:
            open_date = _parse_date(planned)
        if deadlines:
            close_date = _parse_date(deadlines[-1])
    return open_date, close_date


def _is_openish(status_values: list[str], close_date: datetime | None) -> bool:
    now = datetime.now(UTC).replace(tzinfo=None)
    if close_date and close_date < now:
        return False
    return not status_values or any(value not in {"31094503", "closed"} for value in status_values)


class EuFundingTendersConnector:
    source_key = "eu-funding-tenders"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or EU_PORTAL_URL

    async def fetch(self) -> RawSourceResult:
        results: list[dict[str, object]] = []
        seen: set[str] = set()
        for term in EU_TERMS:
            api_key = get_settings().sedia_api_key
            search_url = f"https://api.tech.ec.europa.eu/search-api/prod/rest/search?apiKey={api_key}&text={quote_plus(term)}&pageSize=50&pageNumber=1"
            final_url, content, _ = await fetch_httpx_text(
                search_url,
                method="POST",
                fallback_content_type="application/json",
            )
            payload = json.loads(content)
            for item in payload.get("results") or []:
                identifier = str(item.get("reference") or item.get("metadata", {}).get("identifier", [""])[0]).strip()
                if identifier and identifier in seen:
                    continue
                if identifier:
                    seen.add(identifier)
                results.append(item)
        content = json.dumps({"results": results}, ensure_ascii=False)
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=content,
            content_type="application/json",
            metadata={"terms": EU_TERMS, "result_count": len(results)},
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        payload = json.loads(raw.content)
        items = payload.get("results") or []
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()
        for item in items:
            metadata = item.get("metadata") or {}
            call_titles = metadata.get("callTitle") or []
            title = _clean(_first_text(call_titles) or item.get("summary") or item.get("content"))
            identifiers = metadata.get("identifier") or []
            call_identifiers = metadata.get("callIdentifier") or []
            identifier = _clean(_first_text(identifiers) or _first_text(call_identifiers) or item.get("reference"))
            if not title or not identifier or identifier in seen:
                continue
            status_values = [str(value) for value in (metadata.get("status") or []) if value is not None]
            open_date, close_date = _parse_action_dates(metadata.get("actions") or [])
            if not open_date:
                open_date = _parse_date((metadata.get("startDate") or [None])[0])
            if not close_date:
                close_date = _parse_date((metadata.get("deadlineDate") or [None])[0])
            if not _is_openish(status_values, close_date):
                continue
            seen.add(identifier)
            summary = _clean(item.get("summary") or item.get("content") or title)
            url = EU_TOPIC_URL.format(identifier=identifier)
            budget = metadata.get("budgetOverview")
            if isinstance(budget, list):
                funding_amount_raw = _first_text(budget)
            else:
                funding_amount_raw = str(budget).strip() if budget else None
            candidates.append(
                OpportunityCandidate(
                    title=title[:180],
                    entity="European Commission",
                    country="European Union",
                    official_url=url,
                    summary=summary[:900] or title,
                    categories=["grants", "research", "innovation"],
                    topics=[value for value in (metadata.get("keywords") or [])[:8] if isinstance(value, str)],
                    raw_text=_clean(item.get("content") or json.dumps(item, ensure_ascii=False))[:5000],
                    confidence_score=0.9,
                    open_date=open_date,
                    close_date=close_date,
                    funding_amount_raw=funding_amount_raw,
                )
            )
        return candidates[:50]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or URL")
        if "ec.europa.eu" not in candidate.official_url:
            return ValidationResult(ok=False, reason="URL is outside EU Funding & Tenders")
        return ValidationResult(ok=True)
