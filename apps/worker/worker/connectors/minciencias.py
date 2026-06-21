from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright
from selectolax.parser import HTMLParser, Node

from worker.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from worker.connectors.common import clean_text, fetch_httpx_text, launch_chromium, normalize_text


MINCIENCIAS_URL = "https://minciencias.gov.co/convocatorias/todas"
TITLE_KEYWORDS = ("convocatoria", "convocatorias", "ciencia", "innovacion", "investigacion", "fondo", "programa")
STOP_TITLES = {"inicio", "convocatorias", "convocatorias todas", "todas las convocatorias"}
CLOSED_KEYWORDS = ("cerrada", "cerrado", "closed", "archivada", "archived", "finalizada", "finalizado")
MONTHS_ES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _parse_spanish_date(text: str) -> datetime | None:
    normalized = normalize_text(text)
    match = re.search(r"(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo)?,?\s*([a-z]+)\s+(\d{1,2}),\s*(\d{4})", normalized)
    if not match:
        return None
    month = MONTHS_ES.get(match.group(1))
    if not month:
        return None
    try:
        return datetime(int(match.group(3)), month, int(match.group(2)))
    except ValueError:
        return None


def _extract_money(text: str) -> str | None:
    match = re.search(r"\$\s?[\d\.\,]+", text)
    return match.group(0) if match else None


def _is_candidate_text(text: str) -> bool:
    lowered = normalize_text(text)
    if not lowered or lowered in STOP_TITLES:
        return False
    return any(keyword in lowered for keyword in TITLE_KEYWORDS)


def _is_closed_text(text: str) -> bool:
    lowered = normalize_text(text)
    return any(keyword in lowered for keyword in CLOSED_KEYWORDS)


class MincienciasConnector:
    source_key = "minciencias"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or MINCIENCIAS_URL

    async def fetch(self) -> RawSourceResult:
        try:
            final_url, content, content_type = await fetch_httpx_text(self.base_url, fallback_content_type="text/html")
        except Exception:
            from worker.config import get_settings

            settings = get_settings()
            async with async_playwright() as playwright:
                browser = await launch_chromium(playwright)
                try:
                    page = await browser.new_page(user_agent=settings.scraping_user_agent)
                    await page.goto(self.base_url, wait_until="domcontentloaded", timeout=settings.scraping_timeout_seconds * 1000)
                    await page.wait_for_timeout(4000)
                    content = await page.content()
                    content_type = "text/html"
                    final_url = page.url
                finally:
                    await browser.close()
        return RawSourceResult(source_key=self.source_key, url=final_url, content=content, content_type=content_type)

    def _candidate_from_container(self, container: Node, raw_url: str) -> OpportunityCandidate | None:
        anchor = None
        for link in container.css("a[href]"):
            href = link.attributes.get("href") or ""
            text = clean_text(link.text())
            if href and "/convocatorias/" in href and _is_candidate_text(text):
                anchor = link
                break
        if not anchor:
            return None
        title = _clean(anchor.text())
        href = anchor.attributes.get("href") or ""
        text = _clean(container.text())
        summary = text.replace(title, "", 1).strip(" -:•")
        if not summary:
            summary = title
        if not _is_candidate_text(title):
            return None
        if _is_closed_text(f"{title} {text}"):
            return None
        return OpportunityCandidate(
            title=title[:180],
            entity="Minciencias",
            country="Colombia",
            official_url=urljoin(raw_url, href),
            summary=summary[:900],
            categories=["convocatorias", "ciencia", "innovacion"],
            topics=["minciencias"],
            raw_text=text[:5000],
            confidence_score=0.82,
            open_date=_parse_spanish_date(text),
            funding_amount_raw=_extract_money(text),
            language="es",
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        tree = HTMLParser(raw.content)
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()
        selectors = ("tr", ".views-row", "article", ".view-content li", "li")
        for selector in selectors:
            for container in tree.css(selector):
                candidate = self._candidate_from_container(container, raw.url)
                if not candidate or candidate.official_url in seen:
                    continue
                seen.add(candidate.official_url)
                candidates.append(candidate)

        if candidates:
            return candidates[:50]

        for link in tree.css("a[href]"):
            title = _clean(link.text())
            href = link.attributes.get("href") or ""
            if not title or not href or not _is_candidate_text(title) or "/convocatorias/" not in href:
                continue
            official_url = urljoin(raw.url, href)
            if official_url in seen:
                continue
            seen.add(official_url)
            text = _clean(link.parent.text() if link.parent else title)
            if _is_closed_text(f"{title} {text}"):
                continue
            candidates.append(
                OpportunityCandidate(
                    title=title[:180],
                    entity="Minciencias",
                    country="Colombia",
                    official_url=official_url,
                    summary=text[:900] or title,
                    categories=["convocatorias", "ciencia", "innovacion"],
                    topics=["minciencias"],
                    raw_text=text[:5000],
                    confidence_score=0.72,
                    open_date=_parse_spanish_date(text),
                    funding_amount_raw=_extract_money(text),
                    language="es",
                )
            )
        return candidates[:50]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or URL")
        if urlparse(candidate.official_url).netloc not in {"minciencias.gov.co", "www.minciencias.gov.co"}:
            return ValidationResult(ok=False, reason="URL is outside Minciencias")
        if _is_closed_text(f"{candidate.title} {candidate.summary} {candidate.raw_text}"):
            return ValidationResult(ok=False, reason="Opportunity appears closed")
        return ValidationResult(ok=True)
