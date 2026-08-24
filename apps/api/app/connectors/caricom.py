"""CARICOM procurement tenders connector via HTML scraping."""

from __future__ import annotations

from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import clean_text, fetch_httpx_text
from app.connectors.registry import register

CARICOM_TENDERS_URL = "https://caricom.org/tenders/"
CARICOM_PROCUREMENT_URL = "https://caricom.org/procurement-notices/"


@register("caricom-procurement")
class CaricomConnector:
    source_key = "caricom-procurement"

    def __init__(self, base_url: str | None = None, **kwargs) -> None:
        self.base_url = base_url or CARICOM_TENDERS_URL

    async def fetch(self) -> RawSourceResult:
        final_url, content, content_type = await fetch_httpx_text(
            self.base_url, fallback_content_type="text/html"
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
        # Look for article links and post entries
        for selector in ("article a[href]", "h2 a", "h3 a", ".post-title a", "a[href*='tender']"):
            for link in tree.css(selector):
                title = clean_text(link.text())
                href = link.attributes.get("href") or ""
                if not title or not href or len(title) < 10:
                    continue
                official_url = urljoin(raw.url, href)
                if official_url in seen:
                    continue
                seen.add(official_url)
                candidates.append(
                    OpportunityCandidate(
                        title=title[:180],
                        entity="CARICOM",
                        country="International",
                        official_url=official_url,
                        summary=title[:700],
                        categories=["tenders", "procurement", "caribbean"],
                        topics=["caricom-procurement"],
                        raw_text=title,
                        confidence_score=0.5,
                    )
                )
        if not candidates:
            # Fallback: extract from all links
            for link in tree.css("a[href]"):
                title = clean_text(link.text())
                href = link.attributes.get("href") or ""
                if not title or not href or len(title) < 15:
                    continue
                official_url = urljoin(raw.url, href)
                if official_url in seen:
                    continue
                seen.add(official_url)
                candidates.append(
                    OpportunityCandidate(
                        title=title[:180],
                        entity="CARICOM",
                        country="International",
                        official_url=official_url,
                        summary=title,
                        categories=["tenders", "procurement", "caribbean"],
                        topics=["caricom-procurement"],
                        raw_text=title,
                        confidence_score=0.45,
                    )
                )
        return candidates[:30]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or URL")
        if "caricom.org" not in candidate.official_url:
            return ValidationResult(ok=False, reason="URL is outside CARICOM")
        return ValidationResult(ok=True)
