"""COST Actions open calls connector via WordPress REST API."""
from __future__ import annotations

import re
from datetime import datetime

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import clean_text, fetch_httpx_text, parse_date_text
from app.connectors.registry import register

COST_API_URL = "https://www.cost.eu/wp-json/wp/v2/pages"
COST_TERMS = "open+call"


def _parse_cost_date(value: str | None) -> datetime | None:
    if not value:
        return None
    return parse_date_text(value)


@register("cost-open-calls")
class CostOpenCallsConnector:
    source_key = "cost-open-calls"

    def __init__(self, base_url: str | None = None, **kwargs) -> None:
        self.base_url = base_url or COST_API_URL

    async def fetch(self) -> RawSourceResult:
        url = f"{self.base_url}?search={COST_TERMS}&per_page=20&_fields=id,title,content,excerpt,date,modified,link"
        final_url, content, content_type = await fetch_httpx_text(url, fallback_content_type="application/json")
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=content,
            content_type=content_type,
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        import json
        try:
            items = json.loads(raw.content)
        except json.JSONDecodeError:
            return []
        if isinstance(items, dict):
            items = [items]
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            title_raw = item.get("title", {})
            title = clean_text(title_raw.get("rendered", "") if isinstance(title_raw, dict) else str(title_raw))
            if not title or title in seen:
                continue
            seen.add(title)
            link = str(item.get("link", ""))
            if not link:
                continue
            content_raw = item.get("content", {})
            excerpt_raw = item.get("excerpt", {})
            summary = clean_text(
                (excerpt_raw.get("rendered", "") if isinstance(excerpt_raw, dict) else "")
                or (content_raw.get("rendered", "") if isinstance(content_raw, dict) else "")
            )
            # Extract close date from content if available
            date_match = re.search(r"(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})", summary, re.IGNORECASE)
            close_date = _parse_cost_date(date_match.group(1)) if date_match else None
            raw_date = str(item.get("date", ""))
            open_date = _parse_cost_date(raw_date) if raw_date else None
            candidates.append(
                OpportunityCandidate(
                    title=title[:180],
                    entity="COST Association",
                    country="European Union",
                    official_url=link,
                    summary=summary[:700] or title,
                    categories=["grants", "research", "cooperation", "european cooperation"],
                    topics=["COST", "open call", "research networking"],
                    raw_text=summary[:2500] or title,
                    confidence_score=0.55,
                    open_date=open_date,
                    close_date=close_date,
                )
            )
        return candidates[:30]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or URL")
        if "cost.eu" not in candidate.official_url:
            return ValidationResult(ok=False, reason="URL is outside COST")
        return ValidationResult(ok=True)
