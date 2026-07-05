from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import clean_text, fetch_httpx_text, normalize_text


class UnwomenInnovateConnector:
    source_key = "unwomen-innovate"
    CLOSED_KEYWORDS = (
        "closed",
        "archived",
        "expired",
        "no longer accepting",
        "deadline passed",
        "past deadline",
        "closed call",
    )

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or "https://www.unwomen.org/en/how-we-work/innovation-and-technology"

    async def fetch(self) -> RawSourceResult:
        final_url, content, content_type = await fetch_httpx_text(self.base_url, fallback_content_type="text/html")
        return RawSourceResult(source_key=self.source_key, url=final_url, content=content, content_type=content_type)

    def _title_from_container(self, container) -> tuple[str, str]:
        anchor = container.css_first("a[href]")
        if anchor:
            title = clean_text(anchor.text())
            href = anchor.attributes.get("href") or ""
            if title and href:
                return title, href
        heading = container.css_first("h1, h2, h3, h4")
        if heading:
            return clean_text(heading.text()), ""
        text = clean_text(container.text())
        return text[:180], ""

    def _categories_for_text(self, text: str) -> list[str]:
        lowered = normalize_text(text)
        categories: list[str] = []
        mapping = [
            ("innovation", ["innovation", "innovacion", "innovate"]),
            ("technology", ["technology", "tecnologia", "digital", "ai", "data"]),
            ("gender", ["women", "gender", "equity", "inclusive"]),
            ("cooperation", ["partnership", "cooperation", "collaboration", "network"]),
            ("research", ["research", "science", "lab", "evidence"]),
        ]
        for category, needles in mapping:
            if any(needle in lowered for needle in needles):
                categories.append(category)
        return categories[:4]

    def _date_from_text(self, text: str) -> datetime | None:
        normalized = normalize_text(text)
        for pattern, formats in (
            (r"\b(\d{4}-\d{2}-\d{2})\b", ("%Y-%m-%d",)),
            (r"\b(\d{1,2}/\d{1,2}/\d{4})\b", ("%m/%d/%Y", "%d/%m/%Y")),
            (r"\b([a-z]+ \d{1,2}, \d{4})\b", ("%B %d, %Y", "%b %d, %Y")),
        ):
            match = re.search(pattern, normalized)
            if not match:
                continue
            value = match.group(1)
            for fmt in formats:
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
        return None

    def _is_closed(self, candidate: OpportunityCandidate) -> bool:
        if candidate.close_date and candidate.close_date.date() < datetime.now(UTC).date():
            return True
        normalized = normalize_text(f"{candidate.title} {candidate.summary} {candidate.raw_text}")
        return any(keyword in normalized for keyword in self.CLOSED_KEYWORDS)

    def _candidate(self, title: str, href: str, text: str, raw_url: str) -> OpportunityCandidate | None:
        lowered = normalize_text(f"{title} {text}")
        keywords = ("innovation", "technology", "digital", "women", "gender", "ai", "research", "call", "grant", "fund", "fellowship")
        if not title or not any(keyword in lowered for keyword in keywords):
            return None
        official_url = urljoin(raw_url, href) if href else raw_url
        categories = self._categories_for_text(lowered) or ["innovation", "cooperation"]
        summary = text.replace(title, "", 1).strip(" -:*•")
        return OpportunityCandidate(
            title=title[:180],
            entity="UN Women",
            country="International",
            official_url=official_url,
            summary=summary[:900] or title,
            categories=categories,
            topics=[value for value in categories[:3]],
            raw_text=text[:2500],
            confidence_score=0.78 if href else 0.62,
            close_date=self._date_from_text(text),
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        tree = HTMLParser(raw.content)
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()
        selectors = ("article", "section", "li", ".card", ".teaser", ".views-row", ".content-item")
        for selector in selectors:
            for container in tree.css(selector):
                title, href = self._title_from_container(container)
                text = (container.text() or "").strip()
                candidate = self._candidate(title, href, text, raw.url)
                if not candidate or candidate.official_url in seen or self._is_closed(candidate):
                    continue
                seen.add(candidate.official_url)
                candidates.append(candidate)

        if candidates:
            return candidates[:40]

        for link in tree.css("a[href]"):
            title = clean_text(link.text())
            href = link.attributes.get("href") or ""
            text = clean_text(link.parent.text() if link.parent else title)
            candidate = self._candidate(title, href, text, raw.url)
            if not candidate or candidate.official_url in seen or self._is_closed(candidate):
                continue
            seen.add(candidate.official_url)
            candidates.append(candidate)
        return candidates[:40]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or URL")
        if "unwomen.org" not in candidate.official_url:
            return ValidationResult(ok=False, reason="Unexpected official URL")
        if self._is_closed(candidate):
            return ValidationResult(ok=False, reason="Opportunity appears closed")
        return ValidationResult(ok=True)
