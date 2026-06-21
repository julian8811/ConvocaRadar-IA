from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright
from selectolax.parser import HTMLParser

from worker.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from worker.connectors.common import clean_text, fetch_httpx_text, launch_chromium, parse_date_text


TITLE_KEYWORDS = (
    "convocatoria",
    "fondo",
    "subvencion",
    "innovacion",
    "proyecto",
    "call",
    "grant",
    "funding",
)
STOP_TITLES = {"gobierno", "innovamos", "inicio", "convocatorias"}
SOURCE_ENTITIES = {
    "innovamos-global-innovation-fund": "Innovamos - Global Innovation Fund",
    "innovamos-fid": "Innovamos - Fondo para la Innovacion en el Desarrollo",
}


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _extract_money(text: str) -> str | None:
    patterns = [
        r"\$\s?[\d\.\,]+(?:\s?(?:COP|USD|EUR))?",
        r"USD\s?[\d\.\,]+",
        r"COP\s?[\d\.\,]+",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _clean(match.group(0))
    return None


def _extract_date(text: str) -> datetime | None:
    for pattern, formats in (
        (r"\b(\d{4}-\d{2}-\d{2})\b", ("%Y-%m-%d",)),
        (r"\b(\d{1,2}/\d{1,2}/\d{4})\b", ("%d/%m/%Y", "%m/%d/%Y")),
        (r"\b([A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4})\b", ("%B %d, %Y", "%b %d, %Y")),
        (r"\b(\d{1,2}\s+de\s+[A-Za-zÁÉÍÓÚáéíóúñÑ]+\s+de\s+\d{4})\b", ("%d de %B de %Y",)),
    ):
        match = re.search(pattern, text)
        if not match:
            continue
        value = match.group(1)
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


def _categories_from_text(text: str) -> list[str]:
    lowered = text.lower()
    mapping = [
        ("innovacion", ["innovacion", "innovative", "innovation", "innovate"]),
        ("financiacion", ["fondo", "subvencion", "funding", "grant", "award"]),
        ("cooperacion", ["alianza", "cooperacion", "partnership", "collaboration"]),
        ("investigacion", ["investigacion", "research", "science"]),
        ("sostenibilidad", ["sostenibilidad", "climate", "green", "carbon", "sustainable"]),
    ]
    categories: list[str] = []
    for category, needles in mapping:
        if any(needle in lowered for needle in needles):
            categories.append(category)
    return categories[:4]


class InnovamosConnector:
    def __init__(self, source_key: str, base_url: str | None = None) -> None:
        self.source_key = source_key
        self.base_url = base_url or ""

    def _source_entity(self) -> str:
        return SOURCE_ENTITIES.get(self.source_key, "Innovamos")

    async def _render_page(self, url: str) -> tuple[str, str, str]:
        async with async_playwright() as playwright:
            browser = await launch_chromium(playwright)
            try:
                page = await browser.new_page()
                await page.goto(url, wait_until="networkidle", timeout=60000)
                await page.wait_for_timeout(2000)
                return page.url, await page.content(), "text/html"
            finally:
                await browser.close()

    async def fetch(self) -> RawSourceResult:
        final_url, content, content_type = await fetch_httpx_text(self.base_url, fallback_content_type="text/html")
        if len(content) < 5000 or "ng-app=\"nosune\"" in content or "call.model" in content:
            final_url, content, content_type = await self._render_page(self.base_url)
        return RawSourceResult(source_key=self.source_key, url=final_url, content=content, content_type=content_type)

    def _candidate_from_rendered_page(self, raw: RawSourceResult) -> OpportunityCandidate | None:
        tree = HTMLParser(raw.content)
        title_node = tree.css_first("h1, h2, title")
        page_title = clean_text(title_node.text() if title_node else "")
        body_text = _clean(tree.text())
        title = page_title or self._source_entity()
        if title.lower() in STOP_TITLES:
            title = self._source_entity()
        merged_text = f"{title} {body_text}"
        if not any(keyword in merged_text.lower() for keyword in TITLE_KEYWORDS):
            return None

        organization = ""
        org_node = tree.css_first(".txt-organization")
        if org_node:
            organization = clean_text(org_node.text())
        if not organization:
            organization = self._source_entity()

        status = ""
        for needle in ("Finalizado", "Abierto", "Abierta", "Cerrado", "Cerrada"):
            if needle.lower() in merged_text.lower():
                status = needle
                break

        deadline_line = ""
        deadline_node = tree.css_first(".openClose-deadline")
        if deadline_node:
            deadline_line = clean_text(deadline_node.text())
        date_text = _extract_date(deadline_line or body_text or title)
        money = _extract_money(body_text)

        links = []
        for anchor in tree.css("a[href]"):
            href = anchor.attributes.get("href") or ""
            text = clean_text(anchor.text())
            if not href:
                continue
            official_url = urljoin(raw.url, href)
            if urlparse(official_url).netloc not in {"www.innovamos.gov.co", "innovamos.gov.co", "www.globalinnovation.fund", "globalinnovation.fund"}:
                continue
            if text:
                links.append(official_url)
        links = list(dict.fromkeys(links))
        official_url = raw.url
        application_url = ""
        for link in links:
            if "globalinnovation.fund" in link:
                application_url = link
                break

        summary_parts = []
        for label in ("Descripción", "Objetivo"):
            idx = body_text.find(label)
            if idx != -1:
                summary_parts.append(body_text[idx + len(label): idx + len(label) + 700].strip(" :\n"))
        summary = " ".join(part for part in summary_parts if part) or body_text[:900] or title
        categories = _categories_from_text(merged_text) or ["innovacion", "financiacion"]
        country = "International" if "cualquier país" in merged_text.lower() or "any country" in merged_text.lower() else "Colombia"
        requirements = []
        if "inglés" in merged_text.lower() or "ingles" in merged_text.lower():
            requirements.append("Manejo del idioma inglés")
        if "organización" in merged_text.lower() or "organization" in merged_text.lower():
            requirements.append("Aplicación vía organización afiliada")
        if deadline_line:
            requirements.append(deadline_line)
        return OpportunityCandidate(
            title=title[:180],
            entity=organization[:180],
            country=country,
            official_url=official_url,
            summary=summary[:900] or title,
            categories=categories,
            topics=[self.source_key.replace("-", " "), *categories[:2]],
            requirements=requirements[:5],
            raw_text=body_text[:6000],
            confidence_score=0.92,
            open_date=date_text,
            close_date=date_text,
            funding_amount_raw=money,
            language="es",
        )

    def _candidate_from_container(self, container, raw_url: str) -> OpportunityCandidate | None:
        title = ""
        href = ""
        for anchor in container.css("a[href]"):
            anchor_title = clean_text(anchor.text())
            anchor_href = anchor.attributes.get("href") or ""
            if anchor_title and len(anchor_title) >= 8:
                title = anchor_title
                href = anchor_href
                break
        if not title:
            heading = container.css_first("h1, h2, h3, h4")
            if heading:
                title = clean_text(heading.text())
        if not title:
            return None
        if title.lower() in STOP_TITLES:
            return None
        text = _clean(container.text())
        lowered = f"{title} {text}".lower()
        if not any(keyword in lowered for keyword in TITLE_KEYWORDS):
            return None
        official_url = urljoin(raw_url, href) if href else raw_url
        raw_host = urlparse(raw_url).netloc.lower()
        official_host = urlparse(official_url).netloc.lower()
        if official_host and raw_host and official_host != raw_host and not official_host.endswith(f".{raw_host}"):
            return None
        summary = text.replace(title, "", 1).strip(" -*:")
        categories = _categories_from_text(lowered) or ["innovacion", "financiacion"]
        return OpportunityCandidate(
            title=title[:180],
            entity=self._source_entity(),
            country="Colombia",
            official_url=official_url,
            summary=summary[:900] or title,
            categories=categories,
            topics=[self.source_key.replace("-", " "), *categories[:2]],
            raw_text=text[:5000],
            confidence_score=0.84 if href else 0.7,
            open_date=_extract_date(text),
            language="es",
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        rendered_markers = ("txt-organization", "openClose-deadline", "wrap-deadline", "carousel-content", "globalinnovation.fund")
        if any(marker in raw.content for marker in rendered_markers):
            candidate = self._candidate_from_rendered_page(raw)
            if candidate:
                return [candidate]

        tree = HTMLParser(raw.content)
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()
        selectors = ("article", "section", "li", ".card", ".views-row", ".field--item", ".content-block")
        for selector in selectors:
            for container in tree.css(selector):
                candidate = self._candidate_from_container(container, raw.url)
                if not candidate or candidate.official_url in seen:
                    continue
                seen.add(candidate.official_url)
                candidates.append(candidate)

        if candidates:
            return candidates[:40]

        title_node = tree.css_first("h1, h2, h3, title")
        page_title = clean_text(title_node.text() if title_node else "")
        page_text = _clean(tree.text())
        title = page_title or self._source_entity()
        if title.lower() in STOP_TITLES:
            title = self._source_entity()
        if any(keyword in f"{title} {page_text}".lower() for keyword in TITLE_KEYWORDS):
            return [
                OpportunityCandidate(
                    title=title[:180],
                    entity=self._source_entity(),
                    country="Colombia",
                    official_url=raw.url,
                    summary=page_text[:900] or title,
                    categories=_categories_from_text(page_text) or ["innovacion", "financiacion"],
                    topics=[self.source_key.replace("-", " ")],
                    raw_text=page_text[:5000],
                    confidence_score=0.72,
                    language="es",
                    open_date=_extract_date(page_text),
                )
            ]
        return []

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or URL")
        if urlparse(candidate.official_url).netloc not in {"www.innovamos.gov.co", "innovamos.gov.co", "www.globalinnovation.fund", "globalinnovation.fund"}:
            return ValidationResult(ok=False, reason="URL is outside Innovamos")
        return ValidationResult(ok=True)
