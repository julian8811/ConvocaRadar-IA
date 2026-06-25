from __future__ import annotations

from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from worker.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from worker.connectors.common import BROWSER_UA, clean_text, fetch_httpx_text


GIZ_FUNDING_URL = "https://www.giz.de/en/partner/funding"
GIZ_TENDERS_URL = "https://ausschreibungen.giz.de/"


class GizFundingConnector:
    source_key = "giz-funding"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or GIZ_FUNDING_URL

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
            metadata={"tenders_url": GIZ_TENDERS_URL},
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        tree = HTMLParser(raw.content)
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()

        def add(title: str, href: str, *, summary: str | None = None) -> None:
            cleaned = clean_text(title)
            if not cleaned or len(cleaned) < 12:
                return
            official_url = urljoin(raw.url, href)
            if official_url in seen:
                return
            seen.add(official_url)
            candidates.append(
                OpportunityCandidate(
                    title=cleaned[:180],
                    entity="Deutsche Gesellschaft für Internationale Zusammenarbeit (GIZ)",
                    country="Germany",
                    official_url=official_url,
                    summary=(summary or cleaned)[:700],
                    categories=["cooperation", "development", "funding"],
                    topics=["GIZ", "international cooperation"],
                    raw_text=(summary or cleaned)[:2500],
                    confidence_score=0.65,
                )
            )

        add(
            "GIZ procurement and tender opportunities",
            GIZ_TENDERS_URL,
            summary="Search current GIZ procurement notices and tender opportunities on the Vergabemarktplatz.",
        )
        for anchor in tree.css("a[href]"):
            href = anchor.attributes.get("href") or ""
            title = clean_text(anchor.text())
            if not href or len(title) < 10:
                continue
            lowered = f"{title} {href}".lower()
            if not any(token in lowered for token in ("fund", "partner", "tender", "procure", "project", "download")):
                continue
            if href.endswith(".pdf"):
                continue
            add(title, href)
        return candidates[:20]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        host = urlparse(candidate.official_url).hostname or ""
        allowed = host.endswith("giz.de") or host.endswith("ausschreibungen.giz.de")
        return ValidationResult(ok=bool(candidate.title and allowed))
