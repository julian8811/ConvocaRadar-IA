from app.connectors.registry import register
import json
import re
from datetime import UTC, datetime
from urllib.parse import quote_plus

from app.core.config import get_settings
from app.connectors.common import fetch_httpx_text, thin_fill_candidates
from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult


EU_TOPIC_URL = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/{identifier}"
HORIZON_SEARCH_URL = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
HORIZON_TERMS = ["Horizon Europe", "open call", "research and innovation", "2026", "2027"]


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


@register("horizon-europe-sedia")
class HorizonSediaConnector:
    source_key = "horizon-europe-sedia"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or HORIZON_SEARCH_URL

    async def fetch(self) -> RawSourceResult:
        results: list[dict[str, object]] = []
        seen: set[str] = set()
        final_url = self.base_url
        api_key = get_settings().sedia_api_key or "SEDIA"
        for term in HORIZON_TERMS:
            payload: dict[str, object] = {
                "apiKey": api_key,
                "queryString": term,
                "queryStringLangs": ["en"],
                "pageSize": 50,
                "pageNumber": 1,
                "sort": ["contentDate:desc"],
                "filters": [{"field": "kind", "values": ["call-for-proposals"]}],
            }
            final_url, content, _ = await fetch_httpx_text(
                HORIZON_SEARCH_URL,
                method="POST",
                payload=payload,
                fallback_content_type="application/json",
            )
            payload = json.loads(content)
            for item in payload.get("results") or []:
                metadata = item.get("metadata") or {}
                identifier = _clean(
                    _first_text(metadata.get("identifier"))
                    or _first_text(metadata.get("callIdentifier"))
                    or str(item.get("reference") or "")
                )
                if not identifier or identifier in seen:
                    continue
                seen.add(identifier)
                results.append(item)
        content = json.dumps({"results": results}, ensure_ascii=False)
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=content,
            content_type="application/json",
            metadata={"terms": HORIZON_TERMS, "result_count": len(results)},
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
            identifier = _clean(
                _first_text(identifiers) or _first_text(call_identifiers) or item.get("reference")
            )
            if not title or not identifier or identifier in seen:
                continue
            status_values = [
                str(value) for value in (metadata.get("status") or []) if value is not None
            ]
            open_date, close_date = _parse_action_dates(metadata.get("actions") or [])
            if not open_date:
                open_date = _parse_date(_first_text(metadata.get("startDate")))
            if not close_date:
                close_date = _parse_date(_first_text(metadata.get("deadlineDate")))
            if not _is_openish(status_values, close_date):
                continue
            seen.add(identifier)
            keywords = [
                str(value) for value in (metadata.get("keywords") or []) if isinstance(value, str)
            ]
            candidates.append(
                OpportunityCandidate(
                    title=title[:180],
                    entity="Horizon Europe",
                    country="European Union",
                    official_url=EU_TOPIC_URL.format(identifier=quote_plus(identifier)),
                    summary=_clean(item.get("summary") or title)[:700],
                    categories=["grants", "research", "innovation", "horizon europe"],
                    topics=keywords[:5],
                    raw_text=_clean(item.get("content") or title)[:2500],
                    confidence_score=0.74,
                    open_date=open_date,
                    close_date=close_date,
                )
            )
        return thin_fill_candidates(candidates[:80])

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        return ValidationResult(ok=bool(candidate.title and candidate.official_url))
