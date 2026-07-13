from __future__ import annotations
from app.connectors.registry import register


import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser, Node

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import clean_text, fetch_httpx_text, normalize_text, parse_date_text


MINEDUCACION_URL = "https://www.mineducacion.gov.co/portal/micrositios-institucionales/Cooperacion-Internacional/Becas-convocatorias-y-premios-de-cooperacion-internacional/420940:Becas-y-convocatorias"
TITLE_KEYWORDS = ("convocatoria", "beca", "becas", "cooperacion", "premio", "programa", "fellowship", "grant")
STOP_TITLES = {
    "becas y convocatorias",
    "inicio",
    "cooperacion internacional",
    "becas, convocatorias y premios de cooperacion internacional",
}
COUNTRY_RULES = [
    ("espana", "Spain"),
    ("india", "India"),
    ("singapur", "Singapore"),
    ("portugal", "Portugal"),
    ("chile", "Chile"),
    ("colombia", "Colombia"),
    ("canada", "Canada"),
    ("estados unidos", "United States"),
]


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize_text(value)).strip("-")[:60] or "item"


def _title_match(value: str) -> bool:
    lowered = normalize_text(value)
    if lowered in STOP_TITLES:
        return False
    return any(keyword in lowered for keyword in TITLE_KEYWORDS)


def _country(text: str) -> str:
    lowered = normalize_text(text)
    for needle, country in COUNTRY_RULES:
        if needle in lowered:
            return country
    return "International"



@register("mineducacion-becas")
class MineducacionConnector:
    source_key = "mineducacion-becas"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or MINEDUCACION_URL

    async def fetch(self) -> RawSourceResult:
        final_url, content, content_type = await fetch_httpx_text(self.base_url, fallback_content_type="text/html")
        return RawSourceResult(source_key=self.source_key, url=final_url, content=content, content_type=content_type)

    def _candidate_from_container(self, container: Node, raw_url: str) -> OpportunityCandidate | None:
        title = ""
        href = ""
        for anchor in container.css("a[href]"):
            anchor_title = clean_text(anchor.text())
            anchor_href = anchor.attributes.get("href") or ""
            if anchor_title and _title_match(anchor_title):
                title = anchor_title
                href = anchor_href
                break
        if not title:
            heading = container.css_first("h1, h2, h3, h4")
            if not heading:
                return None
            title = _clean(heading.text())
            if not title or not _title_match(title):
                return None
        text = _clean(container.text())
        summary = text.replace(title, "", 1).strip(" -:*•")
        official_url = urljoin(raw_url, href) if href else f"{raw_url}#{_slug(title)}"
        return OpportunityCandidate(
            title=title[:180],
            entity="Ministerio de Educacion Nacional",
            country=_country(text or title),
            official_url=official_url,
            summary=summary[:1000] or title,
            categories=["becas", "cooperacion", "educacion"],
            topics=["MEN", "cooperacion internacional"],
            raw_text=text[:5000],
            confidence_score=0.86 if href else 0.76,
            open_date=parse_date_text(text),
            language="es",
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        tree = HTMLParser(raw.content)
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()
        selectors = ("article", "section", "li", "div", ".card", ".views-row")
        for selector in selectors:
            for container in tree.css(selector):
                candidate = self._candidate_from_container(container, raw.url)
                if not candidate or candidate.official_url in seen:
                    continue
                if urlparse(candidate.official_url).netloc not in {"www.mineducacion.gov.co", "mineducacion.gov.co"}:
                    continue
                seen.add(candidate.official_url)
                candidates.append(candidate)
        return candidates[:150]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or URL")
        if urlparse(candidate.official_url).netloc not in {"www.mineducacion.gov.co", "mineducacion.gov.co"}:
            return ValidationResult(ok=False, reason="URL is outside MINEDUCACION")
        return ValidationResult(ok=True)
