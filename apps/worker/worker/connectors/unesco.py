from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from worker.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from worker.connectors.common import clean_text, fetch_httpx_text, parse_date_text


UNESCO_HOSTS = {"unesco.org", "www.unesco.org"}



def _title_from(container) -> str:
    heading = container.css_first("h1, h2, h3, h4")
    if heading:
        return clean_text(heading.text())
    anchor = container.css_first("a[href]")
    if anchor:
        return clean_text(anchor.text())
    return ""


class UNESCOConnector:
    source_key = "unesco-call-for-proposals"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or "https://www.unesco.org/en/articles/call-proposals"

    async def fetch(self) -> RawSourceResult:
        final_url, content, content_type = await fetch_httpx_text(self.base_url, fallback_content_type="text/html")
        return RawSourceResult(source_key=self.source_key, url=final_url, content=content, content_type=content_type)

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        tree = HTMLParser(raw.content)
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()
        keywords = ("call for proposals", "proposal", "grant", "funding", "fellowship", "call")

        for selector in ("article", ".card", ".content-item", "section", "li", "tr"):
            for container in tree.css(selector):
                anchor = container.css_first("a[href]")
                title = clean_text(anchor.text()) if anchor else _title_from(container)
                href = anchor.attributes.get("href") if anchor else ""
                text = clean_text(container.text())
                lowered = f"{title} {text}".lower()
                if not title or not href or not any(keyword in lowered for keyword in keywords):
                    continue
                official_url = urljoin(raw.url, href)
                if official_url in seen:
                    continue
                seen.add(official_url)
                candidates.append(
                    OpportunityCandidate(
                        title=title[:180],
                        entity="UNESCO",
                        country="International",
                        official_url=official_url,
                        summary=text[:700] or title,
                        categories=["cooperation", "research", "innovation"],
                        topics=["UNESCO", "proposals"],
                        raw_text=text[:2500],
                        confidence_score=0.68,
                        close_date=parse_date_text(text),
                    )
                )

        if not candidates:
            page_text = clean_text(tree.text())
            if any(keyword in page_text.lower() for keyword in keywords):
                title = clean_text(_title_from(tree) if hasattr(tree, "css_first") else "") or "UNESCO Call for Proposals"
                candidates.append(
                    OpportunityCandidate(
                        title=title[:180],
                        entity="UNESCO",
                        country="International",
                        official_url=raw.url,
                        summary=page_text[:700] or title,
                        categories=["cooperation", "research", "innovation"],
                        topics=["UNESCO", "proposals"],
                        raw_text=page_text[:2500],
                        confidence_score=0.62,
                        close_date=parse_date_text(page_text),
                    )
                )

        return candidates[:25]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or URL")
        if urlparse(candidate.official_url).netloc not in UNESCO_HOSTS:
            return ValidationResult(ok=False, reason="URL is outside UNESCO")
        return ValidationResult(ok=True)
