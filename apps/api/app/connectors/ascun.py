"""ASCUN Colombia convocatorias connector via WordPress REST API."""
from __future__ import annotations

import json
from urllib.parse import urljoin

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import clean_text, fetch_httpx_text, parse_date_text
from app.connectors.registry import register

ASCUN_API_URL = "https://ascun.org.co/wp-json/wp/v2/posts"


@register("ascun-convocatorias")
class AscunConnector:
    source_key = "ascun-convocatorias"

    def __init__(self, base_url: str | None = None, **kwargs) -> None:
        self.base_url = base_url or ASCUN_API_URL

    async def fetch(self) -> RawSourceResult:
        url = f"{self.base_url}?search=convocatoria&per_page=20&_fields=id,title,content,excerpt,date,link"
        final_url, content, content_type = await fetch_httpx_text(url, fallback_content_type="application/json")
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=content,
            content_type=content_type,
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
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
            excerpt_raw = item.get("excerpt", {})
            content_raw = item.get("content", {})
            summary = clean_text(
                (excerpt_raw.get("rendered", "") if isinstance(excerpt_raw, dict) else "")
                or (content_raw.get("rendered", "") if isinstance(content_raw, dict) else "")
            )
            raw_date = str(item.get("date", ""))
            open_date = parse_date_text(raw_date) if raw_date else None
            candidates.append(
                OpportunityCandidate(
                    title=title[:180],
                    entity="ASCUN Colombia",
                    country="Colombia",
                    official_url=link,
                    summary=summary[:700] or title,
                    categories=["convocatorias", "educacion", "cooperacion"],
                    topics=["ascun-convocatorias"],
                    raw_text=summary[:2500] or title,
                    confidence_score=0.55,
                    open_date=open_date,
                )
            )
        return candidates[:30]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or URL")
        if "ascun.org.co" not in candidate.official_url:
            return ValidationResult(ok=False, reason="URL is outside ASCUN")
        return ValidationResult(ok=True)
