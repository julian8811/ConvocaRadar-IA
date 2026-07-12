"""Findeter sitemap-based connector.

Findeter publishes procurement opportunities via a standard XML sitemap.
This connector fetches the sitemap, extracts URLs containing ``/convocatorias/``,
and creates low-confidence candidates from the URL slugs.
"""

from __future__ import annotations

import re
from xml.etree import ElementTree

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import fetch_httpx_text
from app.connectors.registry import register

FINDETER_SITEMAP_URL = "https://www.findeter.gov.co/sitemap.xml"

# Entity codes found in Findeter sitemap URLs mapped to readable names.
ENTITY_CODE_MAP: dict[str, str] = {
    "ICBFGS": "ICBF",
    "ANSPE": "ANSPE",
    "FNG": "Fondo Nacional de Garantías",
    # Add more codes as discovered.
}

_SITEMAP_NS = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# Regex to parse a Findeter convocatoria slug:
# /convocatorias/{ENTITY_CODE}/{TYPE}/{SEQ}-{YEAR}
_CONVOCATORIA_SLUG_RE = re.compile(
    r"/convocatorias/([A-Z]+)/([^/]+)/(\d+)-(\d{4})\b",
    re.IGNORECASE,
)

# Only include URLs from these years (potential active listings).
_ALLOWED_YEARS = frozenset({"2025", "2026"})

_MAX_CANDIDATES = 100


def _resolve_entity_name(code: str) -> str:
    """Map a Findeter entity code to a human-readable name."""
    return ENTITY_CODE_MAP.get(code, code)


@register("findeter-convocatorias")
class FindeterConnector:
    source_key = "findeter-convocatorias"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or FINDETER_SITEMAP_URL

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

        try:
            root = ElementTree.fromstring(raw.content)
        except ElementTree.ParseError:
            return []

        candidates: list[OpportunityCandidate] = []

        for url_elem in root.findall(".//ns:url/ns:loc", _SITEMAP_NS):
            loc = (url_elem.text or "").strip()
            if "/convocatorias/" not in loc:
                continue

            # When the sitemap is served without namespace-awareness,
            # ElementTree may not find elements with the explicit namespace.
            # Fall back: also try bare tag names.
            if not loc:
                continue

            match = _CONVOCATORIA_SLUG_RE.search(loc)
            if not match:
                continue

            entity_code, type_, seq, year = match.groups()

            # Filter to allowed years only.
            if year not in _ALLOWED_YEARS:
                continue

            entity_name = _resolve_entity_name(entity_code)
            title = f"Convocatoria {entity_name} {type_} {seq}-{year}"

            summary = (
                f"Entity: {entity_name} ({entity_code}) | "
                f"Type: {type_} | Sequence: {seq} | Year: {year}"
            )

            candidates.append(
                OpportunityCandidate(
                    title=title,
                    official_url=loc,
                    entity="Findeter",
                    country="Colombia",
                    summary=summary,
                    confidence_score=0.45,
                    categories=["convocatorias", "financiamiento", "infraestructura"],
                    topics=["findeter-convocatorias"],
                )
            )

            if len(candidates) >= _MAX_CANDIDATES:
                break

        return candidates

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title:
            return ValidationResult(ok=False, reason="Missing title")
        if not candidate.official_url or "findeter.gov.co" not in candidate.official_url:
            return ValidationResult(ok=False, reason="Missing or unexpected official URL")
        return ValidationResult(ok=True)
