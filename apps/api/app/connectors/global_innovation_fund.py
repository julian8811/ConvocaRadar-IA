# DEPRECATED: source disabled in seed.py
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import BROWSER_UA, clean_text, fetch_httpx_text


GIF_APPLY_URL = "https://www.globalinnovation.fund/apply-for-funding/"
GIF_ALLOWED_DOMAINS = ["globalinnovation.fund", "www.globalinnovation.fund"]
SKIP_PATHS = {"/apply-for-funding", "/apply-for-funding/", "/news", "/growth"}


class GlobalInnovationFundConnector:
    source_key = "global-innovation-fund"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or GIF_APPLY_URL

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
        body_text = clean_text(tree.text())
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()

        page_title = ""
        for heading in tree.css("h1, h2"):
            text = clean_text(heading.text())
            if text and len(text) > 8:
                page_title = text
                break
        if page_title and raw.url not in seen:
            seen.add(raw.url)
            candidates.append(
                OpportunityCandidate(
                    title=page_title[:180],
                    entity="Global Innovation Fund",
                    country="International",
                    official_url=raw.url,
                    summary=body_text[:900] or page_title,
                    categories=["grants", "innovation", "development", "social impact"],
                    topics=["Global Innovation Fund", "apply for funding"],
                    raw_text=body_text[:2500],
                    confidence_score=0.82,
                    language="en",
                )
            )

        for anchor in tree.css("a[href]"):
            href = anchor.attributes.get("href") or ""
            title = clean_text(anchor.text())
            if not href or not title or len(title) < 12:
                continue
            official_url = urljoin(raw.url, href)
            host = urlparse(official_url).hostname or ""
            if not any(host == domain or host.endswith(f".{domain}") for domain in GIF_ALLOWED_DOMAINS):
                continue
            path = urlparse(official_url).path.rstrip("/") or "/"
            if path in SKIP_PATHS or official_url in seen:
                continue
            lowered = title.lower()
            if not any(token in lowered for token in ("fund", "apply", "guideline", "grant", "invest", "pipeline")):
                continue
            seen.add(official_url)
            candidates.append(
                OpportunityCandidate(
                    title=title[:180],
                    entity="Global Innovation Fund",
                    country="International",
                    official_url=official_url,
                    summary=title[:700],
                    categories=["grants", "innovation", "development"],
                    topics=["Global Innovation Fund"],
                    raw_text=title[:2500],
                    confidence_score=0.74,
                    language="en",
                )
            )
        return candidates[:20]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        host = urlparse(candidate.official_url).hostname or ""
        allowed = any(host == domain or host.endswith(f".{domain}") for domain in GIF_ALLOWED_DOMAINS)
        return ValidationResult(ok=bool(candidate.title and candidate.official_url and allowed))
