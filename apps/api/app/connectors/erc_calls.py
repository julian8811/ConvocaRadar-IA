"""ERC (European Research Council) calls connector via SEDIA API."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import quote_plus

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import fetch_httpx_text
from app.connectors.registry import register

ERC_TOPIC_URL = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/{identifier}"
ERC_SEARCH_URL = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
ERC_QUERY = "ERC"
ERC_TERMS = ["ERC", "European Research Council", "Starting Grant", "Consolidator Grant", "Advanced Grant", "Proof of Concept"]


def _clean(value: str | None) -> str:
    import re
    return re.sub(r"\s+", " ", value or "").strip()


def _first_text(value: object) -> str | None:
    if isinstance(value, list) and value:
        f = value[0]
        return str(f).strip() if f is not None else None
    if isinstance(value, str):
        return value.strip()
    return None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=None)
        except (ValueError, TypeError):
            continue
    return None


@register("erc-calls")
class ErcCallsConnector:
    source_key = "erc-calls"

    def __init__(self, base_url: str | None = None, **kwargs) -> None:
        self.base_url = base_url or ERC_SEARCH_URL

    async def fetch(self) -> RawSourceResult:
        from app.core.config import get_settings
        settings = get_settings()
        api_key = settings.sedia_api_key or "SEDIA"
        # Search for ERC-specific funding topics
        payload = {
            "apiKey": api_key,
            "queryString": "ERC",
            "queryStringLangs": ["en"],
            "pageSize": 50,
            "pageNumber": 1,
            "sort": ["contentDate:desc"],
            "filters": [{"field": "kind", "values": ["call-for-proposals"]}],
        }
        from app.connectors.common import http_client
        client = await http_client()
        response = await client.post(
            self.base_url,
            json=payload,
            timeout=30,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        content = response.text
        return RawSourceResult(
            source_key=self.source_key,
            url=self.base_url,
            content=content,
            content_type="application/json",
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        try:
            payload = json.loads(raw.content)
        except json.JSONDecodeError:
            return []
        results = payload.get("results", payload.get("data", []))
        if isinstance(results, dict):
            results = results.get("results", [])
        candidates: list[OpportunityCandidate] = []
        seen_titles: set[str] = set()
        for item in results:
            if not isinstance(item, dict):
                continue
            title = _clean(str(item.get("title") or item.get("contentTitle") or ""))
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            # Check if ERC-related
            title_lower = title.lower()
            if not any(term.lower() in title_lower for term in ERC_TERMS):
                continue
            identifier = str(item.get("identifier", item.get("id", "")))
            summary = _clean(_first_text(item.get("shortDescription")) or _clean(item.get("description", "")))
            categories = ["grants", "research", "european research council"]
            if "starting" in title_lower:
                categories.append("starting grant")
            if "consolidator" in title_lower:
                categories.append("consolidator grant")
            if "advanced" in title_lower:
                categories.append("advanced grant")
            if "proof of concept" in title_lower or "poc" in title_lower:
                categories.append("proof of concept")
            official_url = ERC_TOPIC_URL.format(identifier=identifier) if identifier else raw.url
            open_date = _parse_date(_first_text(item.get("contentDate")) or _first_text(item.get("startDate")))
            close_date = _parse_date(_first_text(item.get("deadlineDate")) or _first_text(item.get("endDate")))
            candidates.append(
                OpportunityCandidate(
                    title=title[:180],
                    entity="European Research Council",
                    country="European Union",
                    official_url=official_url,
                    summary=summary[:700] or title,
                    categories=categories[:5],
                    topics=["ERC", "horizon europe", "research funding"],
                    raw_text=summary[:2500] or title,
                    confidence_score=0.8,
                    open_date=open_date,
                    close_date=close_date,
                )
            )
        return candidates[:50]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or URL")
        return ValidationResult(ok=True)
