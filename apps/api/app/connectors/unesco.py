from app.connectors.registry import register
from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse
from urllib.parse import unquote

from selectolax.parser import HTMLParser

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import clean_text, fetch_httpx_text, parse_date_text


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
                title = clean_text(_title_from(tree) if hasattr(tree, "css_first") else "") or "UNESCO Call for Proposals"
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

        return candidates[:25]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or URL")
        if urlparse(candidate.official_url).netloc not in UNESCO_HOSTS:
            return ValidationResult(ok=False, reason="URL is outside UNESCO")
        if _is_closed(candidate):
            return ValidationResult(ok=False, reason="Call appears closed")
        return ValidationResult(ok=True)
