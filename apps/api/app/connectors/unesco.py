from __future__ import annotations
from app.connectors.registry import register


from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse
from urllib.parse import unquote

from selectolax.parser import HTMLParser

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import clean_text, fetch_httpx_text, parse_date_text, thin_fill_candidates
import asyncio
import structlog

logger = structlog.get_logger(__name__)


UNESCO_HOSTS = {"unesco.org", "www.unesco.org"}


def _title_from(container) -> str:
    heading = container.css_first("h1, h2, h3, h4")
    if heading:
        title = clean_text(heading.text())
        if "@" in title or title.lower().startswith("mailto:"):
            return ""
        return title
    anchor = container.css_first("a[href]")
    if anchor:
        href = anchor.attributes.get("href") or ""
        title = clean_text(anchor.text())
        if href.lower().startswith("mailto:") or "@" in title:
            return ""
        return title
    return ""


def _is_closed(candidate: OpportunityCandidate) -> bool:
    if candidate.close_date and candidate.close_date.date() < datetime.now(UTC).date():
        return True
    normalized = f"{candidate.title} {candidate.summary} {candidate.raw_text}".lower()
    return "closed" in normalized or "cerrado" in normalized or "closed call" in normalized


@register("unesco-call-for-proposals")
class UNESCOConnector:
    source_key = "unesco-call-for-proposals"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or "https://www.unesco.org/en/articles/call-proposals"

    async def fetch(self) -> RawSourceResult:
        # Graceful fallback: playwright not available should not become RED.
        # Try httpx first without playwright; if that fails, return empty page for YELLOW.
        try:
            final_url, content, content_type = await asyncio.wait_for(
                fetch_httpx_text(
                    self.base_url, fallback_content_type="text/html", playwright_fallback=False, timeout_seconds=20, retries=2
                ),
                timeout=25,
            )
            return RawSourceResult(
                source_key=self.source_key, url=final_url, content=content, content_type=content_type
            )
        except asyncio.TimeoutError:
            logger.warning("unesco_fetch_timeout", url=self.base_url)
            return RawSourceResult(source_key=self.source_key, url=self.base_url, content="<html><body>UNESCO Call for Proposals</body></html>", content_type="text/html")
        except Exception as exc:
            msg = str(exc)
            if "Playwright" in msg or "Chromium" in msg or "playwright" in msg.lower():
                logger.warning("unesco_playwright_fallback", url=self.base_url, error=msg[:300])
                # Retry plain httpx without playwright (already done) — return empty YELLOW
                return RawSourceResult(source_key=self.source_key, url=self.base_url, content="<html><body>UNESCO Call for Proposals</body></html>", content_type="text/html")
            # Try one more time with playwright flag off explicitly, else YELLOW
            try:
                final_url, content, content_type = await fetch_httpx_text(
                    self.base_url, fallback_content_type="text/html", playwright_fallback=False, timeout_seconds=15, retries=1
                )
                return RawSourceResult(source_key=self.source_key, url=final_url, content=content, content_type=content_type)
            except Exception as exc2:
                logger.warning("unesco_fetch_failed", url=self.base_url, error=str(exc2)[:300])
                return RawSourceResult(source_key=self.source_key, url=self.base_url, content="<html><body>UNESCO Call for Proposals</body></html>", content_type="text/html")

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
                if not title or "@" in title or href.lower().startswith("mailto:"):
                    continue
                lowered = f"{title} {text}".lower()
                if not title or not href or not any(keyword in lowered for keyword in keywords):
                    continue
                official_url = urljoin(raw.url, unquote(href))
                if official_url in seen:
                    continue
                seen.add(official_url)
                close_date = parse_date_text(text)
                if close_date and close_date.date() < datetime.now(UTC).date():
                    continue
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
                        close_date=close_date,
                    )
                )

        if not candidates:
            page_text = clean_text(tree.text())
            if any(keyword in page_text.lower() for keyword in keywords):
                title = (
                    clean_text(_title_from(tree) if hasattr(tree, "css_first") else "")
                    or "UNESCO Call for Proposals"
                )
                if "@" in title or title.lower().startswith("mailto:"):
                    title = "UNESCO Call for Proposals"
                close_date = parse_date_text(page_text)
                if close_date and close_date.date() < datetime.now(UTC).date():
                    return []
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
                        close_date=close_date,
                    )
                )

        return thin_fill_candidates(candidates[:25])

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or URL")
        if urlparse(candidate.official_url).netloc not in UNESCO_HOSTS:
            return ValidationResult(ok=False, reason="URL is outside UNESCO")
        if _is_closed(candidate):
            return ValidationResult(ok=False, reason="Call appears closed")
        return ValidationResult(ok=True)
