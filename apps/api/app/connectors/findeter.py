"""Findeter sitemap-based connector.

Findeter publishes procurement opportunities via a standard XML sitemap.
This connector fetches the sitemap, extracts URLs containing ``/convocatorias/``,
and creates low-confidence candidates from the URL slugs.
"""

from __future__ import annotations

import hashlib
import re
import structlog
from datetime import UTC, datetime
from xml.etree import ElementTree

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import enrich_candidates_batch, fetch_httpx_text
from app.connectors.registry import register

logger = structlog.get_logger(__name__)

FINDETER_SITEMAP_URL = "https://www.findeter.gov.co/sitemap.xml"

# Entity prefixes found in Findeter sitemap URLs mapped to readable names.
# The URL format varies widely, so we do prefix matching.
_ENTITY_PREFIX_MAP: dict[str, str] = {
    "paf-euc": "EUC",
    "paf-dps": "DPS",
    "paf-menies": "MEN-IES",
    "paf-ubpd": "UBPD",
    "paf-cpofuntic": "CPO-FUNTIC",
    "paf-viassantander": "VIAS-SANTANDER",
    "paf-fonpaz": "FONPAZ",
    "paf-atminagricultura": "AT-MINAGRICULTURA",
    "paf-menpnie": "MEN-PNIE",
    "paf-icbfgs": "ICBF",
    "paf-aasb": "AASB",
    "paf-atsed": "ATSED",
    "paf-atmininterior": "AT-MININTERIOR",
    "paf-atminsaludcaps": "AT-MINSALUD",
    "paf-colavanza": "COLAVANZA",
    "paf-ciafunticzipaquira": "CIA-FUNTIC-ZIPAQUIRA",
    "paf-atimlcf": "AT-IMLCF",
    "paf-atinvias": "AT-INVIAS",
    "paf-atf": "AT-FINDETER",
    "paf-atbucaramanga": "AT-BUCARAMANGA",
    "paf-atmindeporte": "AT-MINDEPORTE",
    "paf-mib": "MIB",
    "paf-migracioncol": "MIGRACION-COL",
    "paf-invias": "INVIAS",
    "paf-menies": "MEN-IES",
    "paf-minticfomento": "MINTIC-FOMENTO",
    "paf-sena": "SENA",
    "paf-saipro": "SAIPRO",
    "paf-ani": "ANI",
    "paf-feab": "FEAB",
    "paf-artesaniascol": "ARTESANIAS-COL",
    "paf-aticbf": "AT-ICBF",
    "paf-aticbfdapre": "AT-ICBF-DAPRE",
    "paf-atidartes": "AT-IDARTES",
    "paf-atsda": "ATSDA",
    "paf-atmen4": "AT-MEN4",
    "paf-atmen5": "AT-MEN5",
    "paf-hlablanque": "HL-ABLANQUE",
    "paf-menpnie": "MEN-PNIE",
    "paf-iesantamaria": "IE-SANTA-MARIA",
    "paf-feabpopayan": "FEAB-POPAYAN",
    "paf-atmvct": "AT-MVCT",
    "paf-frminexteriores": "FR-MINEXTERIORES",
    "paf-mininterior": "MININTERIOR",
    "paf-mvct": "MVCT",
    "fdt-": "FDT",
    "con-": "CON",
    "cs-": "CS",
    "cia-": "CIA",
    "ccs-": "CCS",
    "inv-": "INV",
}

_SITEMAP_NS = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# Regex to extract year from a convocatoria URL slug.
# Accepts formats like: paf-euc-o-152-2024, con-0413-2025, cs-0085-2025
_CONVOCATORIA_YEAR_RE = re.compile(r"(\d{4})$")

# Only include URLs from these years (potential active listings).
_ALLOWED_YEARS = frozenset({"2024", "2025", "2026"})

_MAX_CANDIDATES = 100


def _resolve_entity_name(code: str) -> str:
    """Map a Findeter entity code to a human-readable name."""
    return _ENTITY_PREFIX_MAP.get(code.lower(), code)


@register("findeter-convocatorias")
class FindeterConnector:
    source_key = "findeter-convocatorias"

    def __init__(self, base_url: str | None = None, **kwargs) -> None:
        # Accept and ignore extra kwargs (entity_name, default_country, etc.)
        self.base_url = base_url or FINDETER_SITEMAP_URL
        self._skip_enrichment = kwargs.get("_skip_enrichment", False)
        # Dedup state: track processed URL hashes across runs
        self._processed_hashes: set[str] = set()
        # Restore state from connector_config if provided
        config = kwargs.get("connector_config")
        if isinstance(config, dict):
            hashes = config.get("processed_hashes")
            if isinstance(hashes, list):
                self._processed_hashes = set(hashes)
                logger.info("findeter_state_restored", count=len(self._processed_hashes))

    def get_updated_config(self) -> dict:
        """Return state dict for the runner to persist."""
        return {"processed_hashes": list(self._processed_hashes)[-5000:]}  # keep last 5k

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

    def _resolve_entity_from_slug(self, slug: str) -> str:
        """Map a URL slug prefix to a readable entity name.

        Tries longest prefix first so ``paf-atminagricultura`` matches
        before ``paf-atm``.
        """
        sorted_prefixes = sorted(_ENTITY_PREFIX_MAP, key=len, reverse=True)
        for prefix in sorted_prefixes:
            if slug.startswith(prefix):
                return _ENTITY_PREFIX_MAP[prefix]
        # Fallback: use first uppercase segment as entity code
        code_match = re.match(r"([A-Z]+)", slug, re.IGNORECASE)
        return _resolve_entity_name(code_match.group(1).upper() if code_match else slug.upper())

    def _make_title(self, path_parts: list[str], slug: str) -> str:
        """Build a human-readable title from convocatoria URL path parts."""
        # Try to extract entity code from path (e.g. ICBFGS, ANSPE)
        entity_code = ""
        for part in path_parts:
            if part.isupper() and len(part) >= 2:
                entity_code = part
                break

        entity = _resolve_entity_name(entity_code) if entity_code else self._resolve_entity_from_slug(slug)

        # Extract a readable type label from the slug or path
        type_codes = {
            "convocatoria": "Convocatoria",
            "licitacion": "Licitación",
            "o": "Obra",
            "i": "Interventoría",
            "s": "Supervisión",
            "ps": "Prestación de Servicios",
            "cs": "Consultoría",
            "c": "Concurso",
            "cv": "Convocatoria",
        }
        type_label = ""
        for part in path_parts + [slug]:
            lower = part.lower().strip("0123456789-")
            if lower in type_codes:
                type_label = f" - {type_codes[lower]}"
                break

        return f"Findeter {entity}{type_label}"[:180]

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        if not raw.content.strip().startswith("<"):
            return []

        try:
            root = ElementTree.fromstring(raw.content)
        except ElementTree.ParseError:
            return []

        candidates: list[OpportunityCandidate] = []

        # Try namespace-aware first, then fall back to bare tags
        for url_elem in root.findall(".//ns:url/ns:loc", _SITEMAP_NS):
            loc = (url_elem.text or "").strip()
            if not loc or "/convocatorias/" not in loc:
                continue

            # Extract the year from the last 4 digits
            year_match = _CONVOCATORIA_YEAR_RE.search(loc)
            if not year_match:
                continue
            year = year_match.group(1)
            if year not in _ALLOWED_YEARS:
                continue

            # Dedup check
            url_hash = hashlib.sha256(loc.encode()).hexdigest()[:16]
            if url_hash in self._processed_hashes:
                continue
            self._processed_hashes.add(url_hash)

            # Extract path parts and slug
            path_parts = loc.rstrip("/").split("/")
            slug = path_parts[-1]
            title = self._make_title(path_parts, slug)

            candidates.append(
                OpportunityCandidate(
                    title=title,
                    official_url=loc,
                    entity="Findeter",
                    country="Colombia",
                    summary=f"Sitemap entry: {slug}",
                    confidence_score=0.45,
                    categories=["convocatorias", "financiamiento", "infraestructura"],
                    topics=["findeter-convocatorias"],
                )
            )

            if len(candidates) >= _MAX_CANDIDATES:
                break

        # Enrich low-confidence candidates from detail pages
        if candidates and not self._skip_enrichment:
            enriched = await enrich_candidates_batch(candidates)
            if enriched:
                return enriched
        return candidates

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title:
            return ValidationResult(ok=False, reason="Missing title")
        if not candidate.official_url or "findeter.gov.co" not in candidate.official_url:
            return ValidationResult(ok=False, reason="Missing or unexpected official URL")
        return ValidationResult(ok=True)
