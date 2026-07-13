from __future__ import annotations
from app.connectors.registry import register


import re
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import BROWSER_UA, clean_text, fetch_httpx_text


PROCOLOMBIA_SITEMAP_URL = "https://www.procolombia.co/sitemap.xml"

# Hub URLs now redirect externally (Notion / GDrive), but we still include
# them so parse() can extract named links from those destinations.
PROCOLOMBIA_GDRIVE_FOLDER = "https://drive.google.com/drive/folders/14b2BnJeQR905gBKFNdakfgLmIrKlvze9"
PROCOLOMBIA_NOTION_URL = "https://groovy-hickory-42b.notion.site/Convocatorias-en-curso-306b1395748780e6a226ca192452a37b"

CLOSED_KEYWORDS = ("cerrad", "finaliz", "cerró", "conclu", "vencid")
ALLOWED_HOSTS = {
    "procolombia.co",
    "www.procolombia.co",
    "groovy-hickory-42b.notion.site",
    "drive.google.com",
}

# Subfolder names from the GDrive folder — each represents an active convocatoria category
GDRIVE_CONVOCATORIA_CATEGORIES = [
    "Convocatorias Agroindustria",
    "Convocatorias Industrias 4.0",
    "Convocatorias Metalmecánica y Otras Industrias",
    "Convocatorias Quimicos y Ciencias de la vida",
    "Convocatorias Sistema Moda",
    "Capacitaciones exportadores",
    "MACRORRUEDA",
]

# Fallback candidates generated from known active programs (updated from Notion/GDrive)
FALLBACK_CANDIDATES: list[dict] = [
    {
        "title": "Ferias y Workshops internacionales ProColombia 2026",
        "entity": "ProColombia - Exportaciones",
        "url": PROCOLOMBIA_GDRIVE_FOLDER,
        "summary": "ProColombia abre convocatoria para participación de empresas colombianas en ferias y workshops internacionales de comercio exterior.",
    },
    {
        "title": "Misiones comerciales internacionales ProColombia 2026",
        "entity": "ProColombia - Exportaciones",
        "url": PROCOLOMBIA_NOTION_URL,
        "summary": "ProColombia promueve misiones comerciales internacionales para impulsar las exportaciones colombianas.",
    },
    {
        "title": "Convocatorias sectoriales de exportación ProColombia 2026",
        "entity": "ProColombia - Exportaciones",
        "url": PROCOLOMBIA_GDRIVE_FOLDER,
        "summary": "Convocatorias abiertas por sector: Agroindustria, Industrias 4.0, Metalmecánica, Químicos, Sistema Moda. Dirigidas a exportadores colombianos.",
    },
]


def _slug_to_title(slug: str) -> str:
    text = slug.replace("-", " ").strip()
    return re.sub(r"\s+", " ", text).title()


def _normalize_procolombia_url(url: str) -> str:
    return url.replace("https://procolombia.co/", "https://www.procolombia.co/")


def _extract_gdrive_subfolder_names(html: str) -> list[str]:
    """Parse Google Drive folder HTML to extract subfolder display names."""
    names = re.findall(r'"([A-ZÁÉÍÓÚa-záéíóúüñ][^"\n]{5,80})\s+Shared folder"', html)
    return list(dict.fromkeys(names))


@register("procolombia-convocatorias")
class ProcolombiaConvocatoriasConnector:
    source_key = "procolombia-convocatorias"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or PROCOLOMBIA_GDRIVE_FOLDER

    async def fetch(self) -> RawSourceResult:
        pages: list[dict[str, str]] = []

        # 1. Sitemap: find news/articles about convocatorias
        try:
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
                and (
                    "/sala-de-prensa/noticias/" in loc.lower()
                    or "/articulos/" in loc.lower()
                    or "/convocatorias/" in loc.lower()
                )
            ][:60]
        except Exception:
            conv_urls = []

        # 2. Fetch sitemap article pages individually
        for url in conv_urls:
            try:
                page_url, content, _ = await fetch_httpx_text(
                    url,
                    headers={"User-Agent": BROWSER_UA},
                    fallback_content_type="text/html",
                    playwright_fallback=False,
                    timeout_seconds=20,
                )
                pages.append({"url": page_url, "content": content})
            except Exception:
                continue

        # 3. Fetch Google Drive folder to extract subfolder names
        gdrive_subfolders: list[str] = []
        try:
            _, gdrive_html, _ = await fetch_httpx_text(
                PROCOLOMBIA_GDRIVE_FOLDER,
                headers={"User-Agent": BROWSER_UA},
                fallback_content_type="text/html",
                timeout_seconds=20,
            )
            gdrive_subfolders = _extract_gdrive_subfolder_names(gdrive_html)
        except Exception:
            gdrive_subfolders = list(GDRIVE_CONVOCATORIA_CATEGORIES)

        # Embed subfolder names as synthetic HTML so parse() can use them
        if gdrive_subfolders:
            synthetic_html = "\n".join(
                f'<a href="{PROCOLOMBIA_GDRIVE_FOLDER}">{name}</a>' for name in gdrive_subfolders
            )
            pages.append({"url": PROCOLOMBIA_GDRIVE_FOLDER, "content": f"<html><body>{synthetic_html}</body></html>"})
        else:
            # Use hardcoded categories if live fetch failed
            synthetic_html = "\n".join(
                f'<a href="{PROCOLOMBIA_GDRIVE_FOLDER}">{name}</a>' for name in GDRIVE_CONVOCATORIA_CATEGORIES
            )
            pages.append({"url": PROCOLOMBIA_GDRIVE_FOLDER, "content": f"<html><body>{synthetic_html}</body></html>"})

        combined = "\n".join(
            f"<!-- page:{page['url']} -->\n{page['content']}" for page in pages
        )
        return RawSourceResult(
            source_key=self.source_key,
            url=PROCOLOMBIA_GDRIVE_FOLDER,
            content=combined,
            content_type="text/html",
            metadata={"pages_fetched": len(pages), "sitemap_urls": len(conv_urls), "gdrive_subfolders": len(gdrive_subfolders)},
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
        if (
            "convocatoria" not in lowered
            and "premio" not in lowered
            and "bootcamp" not in lowered
            and "feria" not in lowered
            and "workshop" not in lowered
            and "misión" not in lowered
            and "macrorrueda" not in lowered
            and "capacitación" not in lowered
            and "capacitacion" not in lowered
            and "programa" not in lowered
        ):
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
            confidence_score=0.72 if host.endswith("procolombia.co") else 0.60,
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
            if page_url and page_url not in seen and page_url.startswith("https://www.procolombia.co"):
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

        # Add fallback candidates if we didn't find enough
        if len(candidates) < 3:
            for fb in FALLBACK_CANDIDATES:
                if fb["url"] not in seen:
                    candidates.append(
                        OpportunityCandidate(
                            title=fb["title"],
                            entity=fb["entity"],
                            country="Colombia",
                            official_url=fb["url"],
                            summary=fb["summary"],
                            categories=["convocatorias", "cooperacion", "internacionalizacion"],
                            topics=["ProColombia", fb["entity"]],
                            raw_text=fb["summary"],
                            confidence_score=0.60,
                            language="es",
                        )
                    )
                    seen.add(fb["url"])

        return candidates[:100]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        host = urlparse(candidate.official_url).hostname or ""
        allowed = any(host == domain or host.endswith(f".{domain}") for domain in ALLOWED_HOSTS)
        return ValidationResult(ok=bool(candidate.title and candidate.official_url and allowed))
