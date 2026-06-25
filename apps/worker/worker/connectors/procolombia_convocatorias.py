from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from worker.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from worker.connectors.common import BROWSER_UA, clean_text, fetch_httpx_text


PROCOLOMBIA_SITEMAP_URL = "https://www.procolombia.co/sitemap.xml"
PROCOLOMBIA_HUB_URLS = (
    "https://www.procolombia.co/convocatorias-exportaciones",
    "https://www.procolombia.co/convocatorias-turismo",
)
CLOSED_KEYWORDS = ("cerrad", "finaliz", "cerró", "cerró", "conclu", "vencid")
ALLOWED_HOSTS = {
    "procolombia.co",
    "www.procolombia.co",
    "groovy-hickory-42b.notion.site",
    "drive.google.com",
}


def _slug_to_title(slug: str) -> str:
    text = slug.replace("-", " ").strip()
    return re.sub(r"\s+", " ", text).title()


def _normalize_procolombia_url(url: str) -> str:
    return url.replace("https://procolombia.co/", "https://www.procolombia.co/")


class ProcolombiaConvocatoriasConnector:
    source_key = "procolombia-convocatorias"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or PROCOLOMBIA_HUB_URLS[0]

    async def fetch(self) -> RawSourceResult:
        pages: list[dict[str, str]] = []
        final_url = self.base_url
        _, sitemap_content, _ = await fetch_httpx_text(
            PROCOLOMBIA_SITEMAP_URL,
            headers={"User-Agent": BROWSER_UA},
            fallback_content_type="application/xml",
            playwright_fallback=False,
        )
        locs = re.findall(r"<loc>([^<]+)</loc>", sitemap_content)
        conv_urls = [
            _normalize_procolombia_url(loc)
            for loc in locs
            if "convocatoria" in loc.lower()
            and ("/sala-de-prensa/noticias/" in loc.lower() or "/articulos/" in loc.lower())
        ][:25]
        for url in [*PROCOLOMBIA_HUB_URLS, *conv_urls]:
            normalized_url = _normalize_procolombia_url(url)
            try:
                page_url, content, _ = await fetch_httpx_text(
                    normalized_url,
                    headers={"User-Agent": BROWSER_UA},
                    fallback_content_type="text/html",
                    playwright_fallback=False,
                    timeout_seconds=25,
                )
                final_url = page_url
                pages.append({"url": page_url, "content": content})
            except Exception:
                continue
        combined = "\n".join(
            f"<!-- page:{page['url']} -->\n{page['content']}" for page in pages
        )
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=combined,
            content_type="text/html",
            metadata={"pages_fetched": len(pages), "news_urls": len(conv_urls)},
        )

    def _candidate_from_url(self, url: str, title: str | None = None) -> OpportunityCandidate | None:
        url = _normalize_procolombia_url(url)
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if host and not any(host == allowed or host.endswith(f".{allowed}") for allowed in ALLOWED_HOSTS):
            return None
        if not title:
            slug = parsed.path.rstrip("/").split("/")[-1]
            title = _slug_to_title(slug)
        title = clean_text(title)
        if not title or len(title) < 12:
            return None
        lowered = title.lower()
        if any(keyword in lowered for keyword in CLOSED_KEYWORDS):
            return None
        if "convocatoria" not in lowered and "premio" not in lowered and "bootcamp" not in lowered:
            if host not in {"groovy-hickory-42b.notion.site", "drive.google.com"}:
                return None
        entity = "ProColombia"
        if "turismo" in lowered or "turismo" in url.lower():
            entity = "ProColombia - Turismo"
        elif "export" in lowered or "export" in url.lower():
            entity = "ProColombia - Exportaciones"
        return OpportunityCandidate(
            title=title[:180],
            entity=entity,
            country="Colombia",
            official_url=url,
            summary=title[:700],
            categories=["convocatorias", "cooperacion", "internacionalizacion"],
            topics=["ProColombia", entity],
            raw_text=title[:2500],
            confidence_score=0.7 if host.endswith("procolombia.co") else 0.65,
            language="es",
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()
        for chunk in raw.content.split("<!-- page:"):
            if "-->" not in chunk:
                continue
            page_url, html = chunk.split("-->", 1)
            page_url = page_url.strip()
            tree = HTMLParser(html)
            title_node = tree.css_first("title, h1")
            page_title = clean_text(title_node.text()) if title_node else ""
            if page_url and page_url not in seen:
                candidate = self._candidate_from_url(page_url, page_title or None)
                if candidate:
                    seen.add(candidate.official_url)
                    candidates.append(candidate)
            for anchor in tree.css("a[href]"):
                href = anchor.attributes.get("href") or ""
                text = clean_text(anchor.text())
                if not href:
                    continue
                official_url = urljoin(page_url or raw.url, href)
                if official_url in seen:
                    continue
                candidate = self._candidate_from_url(official_url, text or None)
                if not candidate:
                    continue
                seen.add(candidate.official_url)
                candidates.append(candidate)
        return candidates[:40]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        host = urlparse(candidate.official_url).hostname or ""
        allowed = any(host == domain or host.endswith(f".{domain}") for domain in ALLOWED_HOSTS)
        return ValidationResult(ok=bool(candidate.title and candidate.official_url and allowed))
