"""Dedicated connector types for Brazilian opportunity portals."""

from __future__ import annotations

import json
import re

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import (
    clean_text,
    fetch_httpx_text,
    parse_date_text,
    thin_fill_candidates,
)
from app.connectors.generic_html import GenericHtmlConnector


class FinepConnector(GenericHtmlConnector):
    """FINEP Brazil connector. Uses GenericHtmlConnector without overrides."""


FAPEMIG_API_URL = (
    "https://api.site.fapemig.br/wp-json/fapemig-chamadas-e-editais/v1/chamadas"
    "?status=aberta"
)
FAPEMIG_DETAIL_URL = "https://fapemig.br/oportunidades/chamadas-e-editais/{slug}"

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(value: str | None) -> str:
    """Collapse an HTML fragment to plain text."""
    return clean_text(_TAG_RE.sub(" ", value or ""))


class FapemigConnector:
    """FAPEMIG chamadas via the public wp-json namespace.

    The legacy seed URL (``/pt/menu/editais/``) 302-redirects to the home
    page and the canonical listing (``/oportunidades/chamadas-e-editais``)
    renders its list client-side (Nuxt CSR, data in ``__NUXT__``), so HTML
    scraping yields zero. The Nuxt frontend reads the WordPress backend at
    ``api.site.fapemig.br``, which exposes
    ``GET /wp-json/fapemig-chamadas-e-editais/v1/chamadas?status=aberta``
    returning structured items (titulo/slug/datas).
    """

    source_key = "fapemig-brasil"

    def __init__(
        self,
        source_key: str,
        base_url: str | None = None,
        **kwargs,
    ) -> None:
        # Accept and ignore extra kwargs (entity_name, default_country, etc.)
        self.source_key = source_key
        self.base_url = base_url or FAPEMIG_API_URL
        self._entity_name = kwargs.get("entity_name") or "FAPEMIG"
        self._default_country = kwargs.get("default_country") or "Brazil"
        self._default_categories = kwargs.get("default_categories") or [
            "convocatorias",
            "ciencia",
            "estadual",
        ]

    async def fetch(self) -> RawSourceResult:
        final_url, content, content_type = await fetch_httpx_text(
            self.base_url,
            fallback_content_type="application/json",
            playwright_fallback=False,
            timeout_seconds=25,
            retries=1,
        )
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=content,
            content_type=content_type,
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        try:
            payload = json.loads(raw.content)
        except (json.JSONDecodeError, TypeError):
            return []
        items = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return []
        candidates: list[OpportunityCandidate] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = clean_text(str(item.get("titulo") or ""))
            slug = str(item.get("slug") or "").strip()
            if not title or not slug:
                continue
            official_url = FAPEMIG_DETAIL_URL.format(slug=slug)
            summary = _strip_tags(item.get("descricao_chamada"))[:700] or title
            candidates.append(
                OpportunityCandidate(
                    title=title[:180],
                    entity=self._entity_name,
                    country=self._default_country,
                    official_url=official_url,
                    summary=summary,
                    raw_text=f"{title} {slug}",
                    confidence_score=0.65,
                    open_date=parse_date_text(item.get("data_inicio_submissao")),
                    close_date=parse_date_text(item.get("data_fim_submissao")),
                    categories=list(self._default_categories),
                    topics=["fapemig-brasil"],
                    external_id=str(item.get("id") or ""),
                )
            )
        return thin_fill_candidates(candidates)

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title.strip():
            return ValidationResult(ok=False, reason="Missing title")
        if not candidate.official_url.strip():
            return ValidationResult(ok=False, reason="Missing official URL")
        return ValidationResult(ok=True)
