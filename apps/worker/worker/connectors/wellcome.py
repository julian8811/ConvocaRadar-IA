from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from urllib.parse import urljoin

from worker.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from worker.connectors.common import clean_text, fetch_httpx_text, parse_date_text


WELLCOME_BASE_URL = "https://wellcome.org/research-funding/schemes"
WELLCOME_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
CLOSED_STATUSES = {"closed", "closed to applications", "not open"}


def _strip_html(value: str | None) -> str:
    return clean_text(re.sub(r"<[^>]+>", " ", value or ""))


class WellcomeConnector:
    source_key = "wellcome-grants"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or WELLCOME_BASE_URL

    async def fetch(self) -> RawSourceResult:
        final_url, content, content_type = await fetch_httpx_text(
            self.base_url,
            headers={"User-Agent": WELLCOME_BROWSER_UA, "Accept": "text/html,application/xhtml+xml"},
            fallback_content_type="text/html",
            playwright_fallback=False,
        )
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
