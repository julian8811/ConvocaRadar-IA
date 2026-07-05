from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import BROWSER_UA, clean_text, fetch_httpx_text, looks_like_noise_text, parse_date_text


CLOSED_KEYWORDS = (
    "terminated",
    "closed",
    "cerrad",
    "finaliz",
    "archiv",
    "upcoming",
)
NOISE_TITLES = {
    "grants & prizes",
    "grants and prizes",
    "apply for grants",
    "open calls",
    "grid",
    "smaller projects",
}
NOISE_KEYWORDS = ("menu", "hovedmenu", "mobil", "footer", "breadcrumb")


class HeadingListHtmlConnector:
    def __init__(
        self,
        source_key: str,
        base_url: str,
        *,
        entity_name: str,
        default_country: str,
        allowed_domains: list[str],
    ) -> None:
        self.source_key = source_key
        self.base_url = base_url
        self.entity_name = entity_name
        self.default_country = default_country
        self.allowed_domains = allowed_domains

    async def fetch(self) -> RawSourceResult:
        final_url, content, content_type = await fetch_httpx_text(
            self.base_url,
            headers={"User-Agent": BROWSER_UA, "Accept": "text/html,application/xhtml+xml"},
            fallback_content_type="text/html",
            playwright_fallback=False,
        )
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=content,
            content_type=content_type,
        )

    def _link_for_heading(self, heading, base_host: str) -> tuple[str, str]:
        anchor = heading.css_first("a[href]")
        if anchor:
            title = clean_text(anchor.text())
            href = anchor.attributes.get("href") or ""
            return title, href
        title = clean_text(heading.text())
        container = heading.parent
        for _ in range(4):
            if container is None:
                break
            anchor = container.css_first("a[href]")
            if anchor:
                href = anchor.attributes.get("href") or ""
                if href and not href.startswith("#"):
                    return title, href
            container = container.parent
        return title, ""

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        tree = HTMLParser(raw.content)
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()
        base_host = urlparse(raw.url).netloc
        for heading in tree.css("h2, h3, h4"):
            title, href = self._link_for_heading(heading, base_host)
            if not title or len(title) < 12:
                continue
            normalized = title.lower()
            if normalized in NOISE_TITLES or looks_like_noise_text(title):
                continue
            if any(keyword in normalized for keyword in NOISE_KEYWORDS):
                continue
            if any(keyword in normalized for keyword in CLOSED_KEYWORDS):
                continue
            if not href:
                continue
            official_url = urljoin(raw.url, href)
            if official_url in seen:
                continue
            seen.add(official_url)
            container = heading.parent
            context = clean_text(container.text()) if container else title
            close_date = parse_date_text(context)
            if close_date and close_date.date() < datetime.now(UTC).date():
                continue
            candidates.append(
                OpportunityCandidate(
                    title=title[:180],
                    entity=self.entity_name,
                    country=self.default_country,
                    official_url=official_url,
                    summary=context[:700] or title[:700],
                    categories=["grants", "research", "health"],
                    topics=[self.entity_name],
                    raw_text=context[:2500] or title[:2500],
                    confidence_score=0.72,
                    close_date=close_date,
                )
            )
        return candidates[:40]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        host = urlparse(candidate.official_url).hostname or ""
        allowed = any(host == domain or host.endswith(f".{domain}") for domain in self.allowed_domains)
        return ValidationResult(ok=bool(candidate.title and candidate.official_url and allowed))
