from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from worker.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from worker.connectors.common import clean_text, fetch_httpx_text, parse_date_text
from worker.connectors.rss import RssConnector


NSF_HOSTS = {"nsf.gov", "www.nsf.gov"}
NSF_CLOSED_KEYWORDS = (
    "closed",
    "archived",
    "expired",
    "no longer accepting",
    "deadline passed",
    "past deadline",
    "solicitation has been replaced",
    "solicitation closed",
)

def _title_from(container) -> str:
    heading = container.css_first("h1, h2, h3, h4")
    if heading:
        return clean_text(heading.text())
    anchor = container.css_first("a[href]")
    if anchor:
        return clean_text(anchor.text())
    return ""


def _is_closed(candidate: OpportunityCandidate) -> bool:
    if candidate.close_date and candidate.close_date.date() < datetime.now(UTC).date():
        return True
    normalized = clean_text(f"{candidate.title} {candidate.summary} {candidate.raw_text}")
    lowered = normalized.lower()
    return any(keyword in lowered for keyword in NSF_CLOSED_KEYWORDS)


class NSFFundingConnector:
    source_key = "nsf-funding"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or "https://www.nsf.gov/funding"

    async def fetch(self) -> RawSourceResult:
        final_url, content, content_type = await fetch_httpx_text(self.base_url, fallback_content_type="text/html")
        return RawSourceResult(source_key=self.source_key, url=final_url, content=content, content_type=content_type)

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        tree = HTMLParser(raw.content)
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()
        keywords = ("funding", "opportunity", "opportunities", "grant", "award", "proposal", "proposals", "call")

        for selector in ("article", ".card", ".views-row", "li", "section", "tr"):
            for container in tree.css(selector):
                anchor = container.css_first("a[href]")
                if not anchor:
                    continue
                title = clean_text(anchor.text()) or _title_from(container)
                href = anchor.attributes.get("href") or ""
                text = clean_text(container.text())
                lowered = f"{title} {text}".lower()
                if not title or not href or not any(keyword in lowered for keyword in keywords):
                    continue
                official_url = urljoin(raw.url, href)
                if official_url in seen:
                    continue
                seen.add(official_url)
                open_date = parse_date_text(text)
                close_date = parse_date_text(text)
                if close_date and close_date.date() < datetime.now(UTC).date():
                    continue
                candidates.append(
                    OpportunityCandidate(
                        title=title[:180],
                        entity="National Science Foundation",
                        country="United States",
                        official_url=official_url,
                        summary=text[:700] or title,
                        categories=["grants", "research", "innovation"],
                        topics=["NSF", "funding"],
                        raw_text=text[:2500],
                        confidence_score=0.72,
                        open_date=open_date,
                        close_date=close_date,
                    )
                )

        if not candidates:
            for link in tree.css("a[href]"):
                title = clean_text(link.text())
                href = link.attributes.get("href") or ""
                lowered = title.lower()
                if not title or not href or not any(keyword in lowered for keyword in keywords):
                    continue
                official_url = urljoin(raw.url, href)
                if official_url in seen:
                    continue
                seen.add(official_url)
                open_date = parse_date_text(title)
                close_date = open_date
                if close_date and close_date.date() < datetime.now(UTC).date():
                    continue
                candidates.append(
                    OpportunityCandidate(
                        title=title[:180],
                        entity="National Science Foundation",
                        country="United States",
                        official_url=official_url,
                        summary=title[:700],
                        categories=["grants", "research", "innovation"],
                        topics=["NSF", "funding"],
                        raw_text=title[:2500],
                        confidence_score=0.6,
                        open_date=open_date,
                        close_date=close_date,
                    )
                )

        return candidates[:40]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or URL")
        if urlparse(candidate.official_url).netloc not in NSF_HOSTS:
            return ValidationResult(ok=False, reason="URL is outside NSF")
        if _is_closed(candidate):
            return ValidationResult(ok=False, reason="Funding opportunity appears closed")
        return ValidationResult(ok=True)


class NSFFundingRssConnector(RssConnector):
    def __init__(self, source_key: str, base_url: str) -> None:
        super().__init__(
            source_key,
            base_url,
            entity="National Science Foundation",
            country="United States",
            categories=["grants", "research", "innovation"],
            topics=["NSF", "funding"],
            confidence_score=0.66,
        )
