"""Sitemap-based connector for Universidad de los Andes convocatorias.

Uniandes publishes convocatoria information as news articles throughout
its site. This connector uses the main XML sitemap to discover URLs
containing "convocatoria" and creates low-confidence candidates from
their URL slugs and context.
"""

from __future__ import annotations

import re
from xml.etree import ElementTree

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import clean_text, enrich_candidates_batch, fetch_httpx_text
from app.connectors.registry import register

UNIANDES_SITEMAP_URL = "https://www.uniandes.edu.co/sitemap.xml"

_SITEMAP_NS = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
_MAX_CANDIDATES = 50


def _title_from_slug(slug: str) -> str:
    """Convert a URL slug into a human-readable title.

    ``hasta-el-7-de-diciembre-esta-abierta-la-convocatoria-para-presentar-proyectos``
    → ``Hasta El 7 De Diciembre Esta Abierta La Convocatoria Para Presentar Proyectos``
    """
    return slug.replace("-", " ").strip().title()


@register("uniandes-investigacion")
class UniandesConnector:
    source_key = "uniandes-investigacion"

    def __init__(self, base_url: str | None = None, **kwargs) -> None:
        # Accept and ignore extra kwargs (entity_name, default_country, etc.)
        self.base_url = base_url or UNIANDES_SITEMAP_URL
        self._skip_enrichment = kwargs.get("_skip_enrichment", False)

    async def fetch(self) -> RawSourceResult:
        final_url, content, content_type = await fetch_httpx_text(
            self.base_url,
            fallback_content_type="application/xml",
        )
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=content,
            content_type=content_type,
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        if not raw.content.strip().startswith("<"):
            return []

        # Try to parse as sitemap index first (with sub-sitemaps),
        # or as a regular urlset.
        try:
            root = ElementTree.fromstring(raw.content)
        except ElementTree.ParseError:
            return []

        # Collect all URLs from either sitemap index or urlset
        urls: list[str] = []

        # Check for sitemap index format
        for sm_elem in root.findall(".//ns:sitemap/ns:loc", _SITEMAP_NS):
            loc = (sm_elem.text or "").strip()
            if loc and "sitemap" in loc.lower():
                urls.append(loc)

        if urls:
            # This is a sitemap index — flatten it
            flat: list[str] = []
            import asyncio

            async def _fetch_sitemap(sub_url: str) -> list[str]:
                try:
                    _url, sub_content, _ct = await fetch_httpx_text(
                        sub_url,
                        fallback_content_type="text/xml",
                        playwright_fallback=False,
                        timeout_seconds=15,
                        retries=1,
                    )
                    sub_root = ElementTree.fromstring(sub_content.encode())
                    return [
                        (loc_elem.text or "").strip()
                        for loc_elem in sub_root.findall(".//ns:url/ns:loc", _SITEMAP_NS)
                        if loc_elem.text
                    ]
                except Exception:
                    return []

            sub_results = await asyncio.gather(*[_fetch_sitemap(u) for u in urls[:20]], return_exceptions=True)
            for entries in sub_results:
                if isinstance(entries, list):
                    flat.extend(entries)
            urls = flat
        else:
            # Direct urlset format
            urls = [
                (loc_elem.text or "").strip()
                for loc_elem in root.findall(".//ns:url/ns:loc", _SITEMAP_NS)
                if loc_elem.text
            ]

        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()

        for loc in urls:
            if not loc or "convocatoria" not in loc.lower():
                continue
            if loc in seen:
                continue
            seen.add(loc)

            slug = loc.rstrip("/").split("/")[-1]
            title = _title_from_slug(slug)[:180]

            # Determine categories from context keywords in URL
            categories = ["convocatorias", "educacion"]
            if "investigacion" in loc.lower() or "investigacion" in loc.lower():
                categories.append("investigacion")
            if "beca" in loc.lower() or "becas" in loc.lower():
                categories.append("becas")
            if "premio" in loc.lower() or "reconocimiento" in loc.lower():
                categories.append("premios")
            if "arte" in loc.lower() or "cultura" in loc.lower():
                categories.append("cultura")

            candidates.append(
                OpportunityCandidate(
                    title=title,
                    official_url=loc,
                    entity="Universidad de los Andes",
                    country="Colombia",
                    summary=f"Convocatoria Uniandes: {slug}",
                    confidence_score=0.45,
                    categories=categories[:5],
                    topics=["uniandes-investigacion"],
                )
            )

            if len(candidates) >= _MAX_CANDIDATES:
                break

        if candidates and not self._skip_enrichment:
            enriched = await enrich_candidates_batch(candidates)
            if enriched:
                return enriched
        return candidates

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title.strip():
            return ValidationResult(ok=False, reason="Missing title")
        if not candidate.official_url.strip():
            return ValidationResult(ok=False, reason="Missing official URL")
        if "uniandes.edu.co" not in candidate.official_url:
            return ValidationResult(ok=False, reason="URL is outside Uniandes")
        return ValidationResult(ok=True)
