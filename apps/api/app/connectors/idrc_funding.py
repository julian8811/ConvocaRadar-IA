# DEPRECATED: source disabled in seed.py
from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import BROWSER_UA, clean_text, fetch_httpx_text, parse_date_text


IDRC_FUNDING_URL = "https://idrc-crdi.ca/en/funding"
CLOSED_KEYWORDS = ("closed", "evaluation of", "upcoming funding opportunity")


class IdrcFundingConnector:
    source_key = "idrc-funding"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or IDRC_FUNDING_URL

    async def fetch(self) -> RawSourceResult:
        final_url, content, content_type = await fetch_httpx_text(
            self.base_url,
            headers={"User-Agent": BROWSER_UA},
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
        tree = HTMLParser(raw.content)
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()
        skip_paths = {
            "/en/funding",
            "/en/funding/applying",
            "/en/funding/managing-funds",
            "/en/funding/resources-idrc-grantees",
            "/en/funding/applying-funding",
        }
        for anchor in tree.css("a[href]"):
            href = anchor.attributes.get("href") or ""
            title = clean_text(anchor.text())
            if not href or not title or len(title) < 18:
                continue
            if not href.startswith("/en/funding/"):
                continue
            path = href.split("?")[0].rstrip("/")
            if path in skip_paths or path.endswith("#financial"):
                continue
            official_url = urljoin("https://idrc-crdi.ca", href)
            if official_url in seen:
                continue
            lowered = title.lower()
            if any(keyword in lowered for keyword in CLOSED_KEYWORDS):
                continue
            if not any(token in lowered for token in ("call", "funding", "grant", "initiative", "award", "partnership", "research")):
                continue
            seen.add(official_url)
            candidates.append(
                OpportunityCandidate(
                    title=title[:180],
                    entity="International Development Research Centre",
                    country="Canada",
                    official_url=official_url,
                    summary=title[:700],
                    categories=["grants", "research", "development", "global"],
                    topics=["IDRC", "international development"],
                    raw_text=title[:2500],
                    confidence_score=0.76,
                )
            )
        return candidates[:40]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        host = urlparse(candidate.official_url).hostname or ""
        return ValidationResult(ok=bool(candidate.title and host.endswith("idrc-crdi.ca")))
