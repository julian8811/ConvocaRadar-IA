from app.connectors.registry import register
from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from urllib.parse import urljoin

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import BROWSER_UA, clean_text, fetch_httpx_text, parse_date_text


WELLCOME_BASE_URL = "https://wellcome.org/research-funding/schemes"
WELLCOME_REQUEST_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-GB,en;q=0.9",
}
CLOSED_STATUSES = {"closed", "closed to applications", "not open"}


def _wellcome_content_is_valid(content: str) -> bool:
    return len(content) >= 1000 and "__NEXT_DATA__" in content


def _strip_html(value: str | None) -> str:
    return clean_text(re.sub(r"<[^>]+>", " ", value or ""))


@register("wellcome-grants")
class WellcomeConnector:
    source_key = "wellcome-grants"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or WELLCOME_BASE_URL

    async def fetch(self) -> RawSourceResult:
        final_url = self.base_url
        content = ""
        content_type = "text/html"
        for attempt in range(4):
            final_url, content, content_type = await fetch_httpx_text(
                self.base_url,
                headers=WELLCOME_REQUEST_HEADERS,
                fallback_content_type="text/html",
                playwright_fallback=False,
                retries=1,
            )
            if _wellcome_content_is_valid(content):
                break
            if attempt < 3:
                await asyncio.sleep(1.5 * (attempt + 1))
        if not _wellcome_content_is_valid(content):
            raise RuntimeError("Wellcome returned an empty or blocked response")
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=content,
            content_type=content_type,
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', raw.content, re.S)
        if not match:
            return []
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return []
        listings = payload.get("props", {}).get("pageProps", {}).get("initialListings") or []
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()
        for item in listings:
            if not isinstance(item, dict):
                continue
            title = clean_text(str(item.get("title") or ""))
            path = clean_text(str(item.get("url") or ""))
            if not title or not path or path in seen:
                continue
            status = clean_text(str(item.get("scheme_status") or item.get("scheme_accepting_applications") or "")).lower()
            if status in CLOSED_STATUSES:
                continue
            close_date = parse_date_text(str(item.get("scheme_closes_for_applications") or ""))
            if not close_date:
                raw_deadline = clean_text(str(item.get("scheme_closes_for_applications") or ""))
                for fmt in ("%d %B %Y", "%d %b %Y"):
                    try:
                        close_date = datetime.strptime(raw_deadline, fmt).replace(tzinfo=UTC).replace(tzinfo=None)
                        break
                    except ValueError:
                        continue
            if close_date and close_date.date() < datetime.now(UTC).date():
                continue
            seen.add(path)
            summary = _strip_html(str(item.get("listing_summary") or title))
            funding = _strip_html(str(item.get("level_of_funding") or ""))
            if funding:
                summary = f"{summary} Funding: {funding}."
            topics = [
                clean_text(str(topic.get("name") or topic.get("title") or ""))
                for topic in (item.get("linked_strategic_programmes") or [])
                if isinstance(topic, dict)
            ]
            topics = [topic for topic in topics if topic]
            candidates.append(
                OpportunityCandidate(
                    title=title[:180],
                    entity="Wellcome Trust",
                    country="United Kingdom",
                    official_url=urljoin("https://wellcome.org", path),
                    summary=summary[:700],
                    categories=["grants", "health", "research"],
                    topics=topics[:5],
                    raw_text=summary[:2500],
                    confidence_score=0.78,
                    close_date=close_date,
                )
            )
        return candidates[:50]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        return ValidationResult(ok=bool(candidate.title and candidate.official_url.startswith("https://wellcome.org/")))
