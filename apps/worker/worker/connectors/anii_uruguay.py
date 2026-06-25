from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from worker.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from worker.connectors.common import BROWSER_UA, clean_text, fetch_httpx_text, parse_date_text


ANII_CATEGORY_URLS = (
    "https://anii.org.uy/apoyos/investigacion/",
    "https://anii.org.uy/apoyos/innovacion/",
    "https://anii.org.uy/apoyos/formacion/",
    "https://anii.org.uy/apoyos/emprendimientos/",
)
ANII_CONVOCATORIA_PATTERN = re.compile(r"/apoyos/[^/]+/\d+/[^/?#]+")
CLOSED_KEYWORDS = (
    "informe de cierre",
    "informe-cierre",
    "resolución",
    "resolucion",
    "cerrad",
    "finaliz",
    "conclu",
)
NOISE_TITLES = {"índice", "indice", "investigación", "investigacion", "innovación", "innovacion", "formación", "formacion", "emprendimientos", "cooperación", "cooperacion", "documentos útiles", "documentos utiles", "ver calendario", "ver todas"}


class AniiUruguayConnector:
    source_key = "anii-uruguay"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or ANII_CATEGORY_URLS[0]

    async def fetch(self) -> RawSourceResult:
        pages: list[dict[str, str]] = []
        final_url = self.base_url
        for url in ANII_CATEGORY_URLS:
            page_url, content, _ = await fetch_httpx_text(
                url,
                headers={"User-Agent": BROWSER_UA},
                fallback_content_type="text/html",
                playwright_fallback=False,
            )
            final_url = page_url
            pages.append({"url": page_url, "content": content})
        combined = "\n".join(
            f"<!-- page:{page['url']} -->\n{page['content']}" for page in pages
        )
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=combined,
            content_type="text/html",
            metadata={"pages_fetched": len(pages)},
        )

    def _normalize_url(self, href: str, base_url: str) -> str:
        official_url = urljoin(base_url, href)
        parsed = urlparse(official_url)
        host = parsed.hostname or ""
        if host.endswith("anii.org.uy"):
            official_url = official_url.replace("://www.anii.org.uy", "://anii.org.uy")
        return official_url.split("#")[0].split("?")[0]

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()
        for chunk in raw.content.split("<!-- page:"):
            if "-->" not in chunk:
                continue
            page_url, html = chunk.split("-->", 1)
            page_url = page_url.strip()
            tree = HTMLParser(html)
            for anchor in tree.css("a[href]"):
                href = anchor.attributes.get("href") or ""
                title = clean_text(anchor.text())
                if not href or not title or len(title) < 10:
                    continue
                path = urlparse(urljoin(page_url, href)).path
                if not ANII_CONVOCATORIA_PATTERN.search(path):
                    continue
                lowered_title = title.lower()
                lowered_href = href.lower()
                if any(keyword in lowered_title for keyword in NOISE_TITLES):
                    continue
                if any(keyword in lowered_href for keyword in CLOSED_KEYWORDS):
                    continue
                if any(keyword in lowered_title for keyword in ("informe", "resolución", "resolucion", "pdf")):
                    continue
                official_url = self._normalize_url(href, page_url)
                if official_url in seen:
                    continue
                seen.add(official_url)
                context = title
                container = anchor.parent
                if container is not None:
                    context = clean_text(container.text()) or title
                close_date = parse_date_text(context)
                candidates.append(
                    OpportunityCandidate(
                        title=title[:180],
                        entity="ANII Uruguay",
                        country="Uruguay",
                        official_url=official_url,
                        summary=context[:700] or title[:700],
                        categories=["convocatorias", "investigacion", "innovacion"],
                        topics=["ANII", "Uruguay"],
                        raw_text=context[:2500] or title[:2500],
                        confidence_score=0.76,
                        close_date=close_date,
                        language="es",
                    )
                )
        return candidates[:80]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        host = urlparse(candidate.official_url).hostname or ""
        return ValidationResult(ok=bool(candidate.title and host.endswith("anii.org.uy")))
