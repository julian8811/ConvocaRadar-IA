from app.connectors.registry import register
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import clean_text, extract_close_date, fetch_httpx_text, parse_date_text


UKRI_HOSTS = {"ukri.org", "www.ukri.org"}



def _title_from(container) -> str:
    heading = container.css_first("h1, h2, h3, h4")
    if heading:
        return clean_text(heading.text())
    anchor = container.css_first("a[href]")
    if anchor:
        return clean_text(anchor.text())
    return ""


@register("ukri-opportunities")
class UKRIConnector:
    source_key = "ukri-opportunities"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or "https://www.ukri.org/opportunity/"

    async def fetch(self) -> RawSourceResult:
        final_url, content, content_type = await fetch_httpx_text(self.base_url, fallback_content_type="text/html")
        return RawSourceResult(source_key=self.source_key, url=final_url, content=content, content_type=content_type)

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        tree = HTMLParser(raw.content)
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()
        keywords = ("opportunity", "funding", "grant", "award", "call", "proposal", "proposals", "competition")

        for selector in ("article", ".card", ".cards__item", ".list-item", "li", "section", "tr"):
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
                categories = ["grants", "research", "innovation"]
                if any(word in lowered for word in ("phd", "doctorate", "studentship")):
                    categories = ["fellowship", "research", "education"]
                candidates.append(
                    OpportunityCandidate(
                        title=title[:180],
                        entity="UK Research and Innovation",
                        country="United Kingdom",
                        official_url=official_url,
                        summary=text[:700] or title,
                        categories=categories,
                        topics=["UKRI", "funding"],
                        raw_text=text[:2500],
                        confidence_score=0.7,
                        open_date=parse_date_text(text),
                        close_date=extract_close_date(text),
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
                candidates.append(
                    OpportunityCandidate(
                        title=title[:180],
                        entity="UK Research and Innovation",
                        country="United Kingdom",
                        official_url=official_url,
                        summary=title[:700],
                        categories=["grants", "research", "innovation"],
                        topics=["UKRI", "funding"],
                        raw_text=title[:2500],
                        confidence_score=0.58,
                    )
                )

        return candidates[:40]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or URL")
        if urlparse(candidate.official_url).netloc not in UKRI_HOSTS:
            return ValidationResult(ok=False, reason="URL is outside UKRI")
        return ValidationResult(ok=True)
