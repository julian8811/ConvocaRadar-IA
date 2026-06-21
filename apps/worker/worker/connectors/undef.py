from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from worker.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from worker.connectors.common import clean_text, fetch_httpx_text, parse_date_text


UNDEF_URL = "https://www.un.org/democracyfund/en/apply-for-funding"
TITLE_KEYWORDS = ("call", "proposal", "proposals", "fund", "grant", "application", "funding", "opportunity")
STOP_TITLES = {"apply for funding", "united nations democracy fund", "undef"}


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


class UNDEFConnector:
    source_key = "undef"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or UNDEF_URL

    async def fetch(self) -> RawSourceResult:
        final_url, content, content_type = await fetch_httpx_text(self.base_url, fallback_content_type="text/html")
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=content,
            content_type=content_type,
        )

    def _candidate_from_container(self, container, raw_url: str) -> OpportunityCandidate | None:
        anchor = container.css_first("a[href]")
        title = clean_text(anchor.text()) if anchor else ""
        href = anchor.attributes.get("href") if anchor else ""
        if not title:
            heading = container.css_first("h1, h2, h3, h4")
            if heading:
                title = clean_text(heading.text())
        if not title or title.lower() in STOP_TITLES:
            return None
        text = _clean(container.text())
        lowered = f"{title} {text}".lower()
        if not any(keyword in lowered for keyword in TITLE_KEYWORDS):
            return None
        official_url = urljoin(raw_url, href) if href else raw_url
        summary = text.replace(title, "", 1).strip(" -*:")
        return OpportunityCandidate(
            title=title[:180],
            entity="United Nations Democracy Fund",
            country="International",
            official_url=official_url,
            summary=summary[:900] or title,
            categories=["cooperation", "funding", "governance"],
            topics=["UNDEF", "democracy"],
            raw_text=text[:5000],
            confidence_score=0.8 if href else 0.68,
            language="en",
            close_date=parse_date_text(text),
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        tree = HTMLParser(raw.content)
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()
        selectors = ("article", "section", "li", ".card", ".teaser", ".views-row", ".field--item")
        for selector in selectors:
            for container in tree.css(selector):
                candidate = self._candidate_from_container(container, raw.url)
                if not candidate or candidate.official_url in seen:
                    continue
                seen.add(candidate.official_url)
                candidates.append(candidate)

        if candidates:
            return candidates[:30]

        page_text = re.sub(r"\s+", " ", tree.text() or "").strip()
        heading = tree.css_first("h1, h2, h3")
        title = clean_text(heading.text()) if heading else "UNDEF funding call"
        if title.lower() in STOP_TITLES:
            title = "UNDEF funding call"
        if any(keyword in f"{title} {page_text}".lower() for keyword in TITLE_KEYWORDS):
            return [
                OpportunityCandidate(
                    title=title[:180],
                    entity="United Nations Democracy Fund",
                    country="International",
                    official_url=raw.url,
                    summary=page_text[:900] or title,
                    categories=["cooperation", "funding", "governance"],
                    topics=["UNDEF", "democracy"],
                    raw_text=page_text[:5000],
                    confidence_score=0.7,
                    language="en",
                    close_date=parse_date_text(page_text),
                )
            ]
        return []

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or URL")
        if urlparse(candidate.official_url).netloc not in {"www.un.org", "un.org"}:
            return ValidationResult(ok=False, reason="URL is outside UNDEF")
        return ValidationResult(ok=True)
