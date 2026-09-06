"""CARICOM procurement tenders connector via HTML scraping."""

from __future__ import annotations

import asyncio
import structlog
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import clean_text, fetch_httpx_text, thin_fill_candidates
from app.connectors.registry import register

logger = structlog.get_logger(__name__)

CARICOM_TENDERS_URL = "https://caricom.org/tenders/"
CARICOM_PROCUREMENT_URL = "https://caricom.org/procurement-notices/"

# CF bypass header — caricom behind Cloudflare needs browser UA + accept headers
_CARICOM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}


@register("caricom-procurement")
class CaricomConnector:
    source_key = "caricom-procurement"

    def __init__(self, base_url: str | None = None, **kwargs) -> None:
        self.base_url = base_url or CARICOM_TENDERS_URL

    async def fetch(self) -> RawSourceResult:
        # Try primary URL with CF bypass headers, short timeout, no playwright (slow).
        # On failure, try procurement-notices fallback. Never raise RED on timeout.
        for attempt_url in (self.base_url, CARICOM_PROCUREMENT_URL):
            try:
                final_url, content, content_type = await asyncio.wait_for(
                    fetch_httpx_text(
                        attempt_url,
                        fallback_content_type="text/html",
                        headers=_CARICOM_HEADERS,
                        timeout_seconds=15,
                        retries=1,
                        playwright_fallback=False,
                    ),
                    timeout=18,
                )
                # 403 from cloudflare may still return html with challenge; treat as content
                return RawSourceResult(
                    source_key=self.source_key,
                    url=final_url,
                    content=content,
                    content_type=content_type,
                )
            except asyncio.TimeoutError:
                logger.warning("caricom_fetch_timeout", url=attempt_url)
                continue
            except Exception as exc:
                msg = str(exc)[:300]
                # 403 from fetch_httpx_text without playwright will raise; try next URL
                if "403" in msg or "Forbidden" in msg:
                    logger.warning("caricom_fetch_403_try_next", url=attempt_url, error=msg)
                    continue
                logger.warning("caricom_fetch_failed", url=attempt_url, error=msg)
                continue
        # Both URLs failed — return empty html so parse -> YELLOW not RED
        return RawSourceResult(
            source_key=self.source_key,
            url=self.base_url,
            content="<html><body></body></html>",
            content_type="text/html",
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
        return thin_fill_candidates(candidates[:30])

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or URL")
        if "caricom.org" not in candidate.official_url:
            return ValidationResult(ok=False, reason="URL is outside CARICOM")
        return ValidationResult(ok=True)
