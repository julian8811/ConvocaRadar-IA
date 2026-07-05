from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from worker.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from worker.connectors.common import clean_text, fetch_httpx_text, normalize_text, parse_date_text


APC_URLS = [
    "https://www.apccolombia.gov.co/seccion/modalidades-de-cooperacion",
    "https://www.apccolombia.gov.co/seccion/modalidades-de-cooperacion?page=2",
    "https://www.apccolombia.gov.co/seccion/modalidades-de-cooperacion?page=3",
    "https://www.apccolombia.gov.co/seccion/modalidades-de-cooperacion?page=4",
    "https://www.apccolombia.gov.co/seccion/modalidades-de-cooperacion?page=5",
    "https://www.apccolombia.gov.co/seccion/modalidades-de-cooperacion?page=6",
    "https://www.apccolombia.gov.co/modalidades-de-cooperacion/convocatorias/otras-convocatorias",
]

TITLE_KEYWORDS = ("convocatoria", "cooperacion", "voluntariado", "ayuda", "grant", "call")
CLOSED_KEYWORDS = ("cerrada", "cerrado", "closed", "archivada", "archived", "finalizada")
GENERIC_TITLE_KEYWORDS = {
    normalize_text(value)
    for value in (
        "aqui",
        "aquí",
        "lee mas sobre",
        "lee más sobre",
        "formato de postulación",
        "preguntas frecuentes",
        "siguiente página",
        "convocatorias",
        "cooperación triangular",
        "aviso de confidencialidad",
        "mapa del sitio",
        "suscribirse",
    )
}


def _clean(value: str | None) -> str:
    return clean_text(value)


def _is_candidate_text(value: str) -> bool:
    lowered = normalize_text(value)
    return any(keyword in lowered for keyword in TITLE_KEYWORDS)


def _is_closed_text(value: str) -> bool:
    lowered = normalize_text(value)
    return any(keyword in lowered for keyword in CLOSED_KEYWORDS)


def _is_generic_title(value: str) -> bool:
    lowered = normalize_text(value)
    if not lowered:
        return True
    if lowered in GENERIC_TITLE_KEYWORDS:
        return True
    return any(lowered.startswith(keyword) for keyword in GENERIC_TITLE_KEYWORDS)


class ApcColombiaConnector:
    source_key = "apc-colombia"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or APC_URLS[0]

    async def fetch(self) -> RawSourceResult:
        pages: list[dict[str, str]] = []
        for url in APC_URLS:
            final_url, content, _ = await fetch_httpx_text(url, fallback_content_type="text/html")
            pages.append({"url": final_url, "content": content})
        combined = "\n<!-- APC_PAGE_BREAK -->\n".join(page["content"] for page in pages)
        return RawSourceResult(source_key=self.source_key, url=self.base_url, content=combined, content_type="text/html", metadata={"pages": pages})

    def _candidate_from_anchor(self, anchor, page_url: str, container_text: str) -> OpportunityCandidate | None:
        title = clean_text(anchor.text())
        href = anchor.attributes.get("href") or ""
        if not title or not href:
            return None
        if _is_generic_title(title):
            return None
        if "color:" in normalize_text(title) or "background-color:" in normalize_text(title):
            return None
        lowered = normalize_text(f"{title} {container_text}")
        if not _is_candidate_text(lowered):
            return None
        official_url = urljoin(page_url, href)
        if urlparse(official_url).netloc not in {"www.apccolombia.gov.co", "portalservicios-apccolombia.gov.co"}:
            return None
        summary = container_text.replace(title, "", 1).strip(" -:*•")
        status = "Abierta" if "abierta" in lowered else "Cerrada" if "cerrada" in lowered else ""
        if status and status.lower() not in summary.lower():
            summary = f"{status}. {summary}".strip()
        date_match = re.search(r"(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})", container_text)
        open_date = parse_date_text(date_match.group(1) if date_match else container_text)
        if _is_closed_text(title):
            return None
        return OpportunityCandidate(
            title=title[:180],
            entity="APC Colombia",
            country="Colombia",
            official_url=official_url,
            summary=summary[:800] or title,
            categories=["cooperacion", "convocatorias"],
            topics=["apc-colombia"],
            raw_text=container_text[:3000],
            confidence_score=0.82,
            open_date=open_date,
            language="es",
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        pages = raw.metadata.get("pages") or [{"url": raw.url, "content": raw.content}]
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()
        for page in pages:
            page_url = str(page["url"])
            tree = HTMLParser(str(page["content"]))
            containers = [*tree.css("article.page.teaser"), *tree.css(".az-text"), *tree.css(".field--item"), *tree.css("article"), *tree.css("section")]
            for container in containers:
                container_text = _clean(container.text())
                for anchor in container.css("a[href]"):
                    candidate = self._candidate_from_anchor(anchor, page_url, container_text)
                    if not candidate or candidate.official_url in seen:
                        continue
                    seen.add(candidate.official_url)
                    candidates.append(candidate)

        if candidates:
            return candidates[:150]

        for page in pages:
            page_url = str(page["url"])
            tree = HTMLParser(str(page["content"]))
            for link in tree.css("a[href]"):
                title = clean_text(link.text())
                if not title or _is_generic_title(title) or not _is_candidate_text(title):
                    continue
                official_url = urljoin(page_url, link.attributes.get("href") or "")
                if official_url in seen:
                    continue
                if urlparse(official_url).netloc not in {"www.apccolombia.gov.co", "portalservicios-apccolombia.gov.co"}:
                    continue
                seen.add(official_url)
                if _is_closed_text(title):
                    continue
                candidates.append(
                    OpportunityCandidate(
                        title=title[:180],
                        entity="APC Colombia",
                        country="Colombia",
                        official_url=official_url,
                        summary=title[:800],
                        categories=["cooperacion", "convocatorias"],
                        topics=["apc-colombia"],
                        raw_text=title[:3000],
                        confidence_score=0.68,
                        language="es",
                    )
                )
        return candidates[:100]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or URL")
        if "apccolombia.gov.co" not in candidate.official_url and "portalservicios-apccolombia.gov.co" not in candidate.official_url:
            return ValidationResult(ok=False, reason="URL is outside APC Colombia")
        if _is_closed_text(f"{candidate.title} {candidate.summary} {candidate.raw_text}"):
            return ValidationResult(ok=False, reason="Opportunity appears closed")
        return ValidationResult(ok=True)
