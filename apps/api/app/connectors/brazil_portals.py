"""Dedicated connector types for Brazilian opportunity portals."""

from __future__ import annotations

import json
import re

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import (
    clean_text,
    fetch_httpx_text,
    parse_date_text,
    thin_fill_candidates,
)


FINEP_API_URL = (
    "https://www.finep.gov.br/o/c/chamadapublicas?sort=dataDePublicacao:desc"
)
FINEP_LISTING_URL = "https://www.finep.gov.br/oportunidades"
_FINEP_PAGE_SIZE = 500
_FINEP_MAX_PAGES = 10


def _with_page(base_url: str, page: int, page_size: int) -> str:
    """Merge ``page``/``pageSize`` into an existing query string."""
    parts = urlparse(base_url)
    query = dict(parse_qsl(parts.query))
    query["page"] = str(page)
    query["pageSize"] = str(page_size)
    return urlunparse(parts._replace(query=urlencode(query)))


_ISO_DATETIME = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ]")


def _iso_date(value: str | None) -> str | None:
    """Trim an ISO datetime (``2027-04-30T17:00:00``) to its date part.

    Connector-local: ``parse_date_text`` only matches ``YYYY-MM-DD`` on a
    word boundary, and the ``T`` separator breaks ``\\b``. No global change.
    """
    text = clean_text(value)
    if not text:
        return None
    match = _ISO_DATETIME.match(text)
    return match.group(1) if match else text


class FinepConnector:
    """FINEP chamadas via the public Liferay headless custom-object API.

    The landing (``/oportunidades``) renders its list client-side (bundle
    ``/o/finep-busca-chamadas-publicas/``) so HTML scraping yields zero.
    The bundle reads ``GET /o/c/chamadapublicas`` (no auth, paginated;
    ``pageSize=500`` returns the whole catalog in one page) with items
    carrying titulo/situacao (aberta/encerrada)/prazos.
    """

    source_key = "finep-brasil"

    def __init__(
        self,
        source_key: str,
        base_url: str | None = None,
        **kwargs,
    ) -> None:
        # Accept and ignore extra kwargs (entity_name, default_country, etc.)
        self.source_key = source_key
        self.base_url = base_url or FINEP_API_URL
        self._entity_name = kwargs.get("entity_name") or "FINEP"
        self._default_country = kwargs.get("default_country") or "Brazil"
        self._default_categories = kwargs.get("default_categories") or [
            "convocatorias",
            "innovacion",
            "brasil",
        ]

    async def fetch(self) -> RawSourceResult:
        merged: list[dict] = []
        total: int | None = None
        final_url = self.base_url
        page = 1
        while page <= _FINEP_MAX_PAGES:
            url = _with_page(self.base_url, page, _FINEP_PAGE_SIZE)
            final_url, content, content_type = await fetch_httpx_text(
                url,
                fallback_content_type="application/json",
                playwright_fallback=False,
                timeout_seconds=25,
                retries=1,
            )
            try:
                payload = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                break
            items = payload.get("items") if isinstance(payload, dict) else payload
            if not isinstance(items, list):
                break
            if isinstance(payload, dict) and total is None:
                total = payload.get("totalCount")
            merged.extend(x for x in items if isinstance(x, dict))
            if len(items) < _FINEP_PAGE_SIZE:
                break
            page += 1
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=json.dumps({"items": merged, "totalCount": total}),
            content_type="application/json",
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        try:
            payload = json.loads(raw.content)
        except (json.JSONDecodeError, TypeError):
            return []
        items = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return []
        candidates: list[OpportunityCandidate] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            situacao = item.get("situacao") or {}
            situacao_key = situacao.get("key", "") if isinstance(situacao, dict) else ""
            # Only open calls (plus unlabelled but still current ones);
            # "encerrada" history stays out of the catalog.
            if situacao_key not in ("aberta", ""):
                continue
            title = clean_text(str(item.get("titulo") or ""))
            if not title:
                continue
            summary = (
                _strip_tags(item.get("descricao"))[:700]
                or clean_text(str(item.get("descricaoRawText") or ""))[:700]
                or title
            )
            candidates.append(
                OpportunityCandidate(
                    title=title[:180],
                    entity=self._entity_name,
                    country=self._default_country,
                    official_url=FINEP_LISTING_URL,
                    summary=summary,
                    raw_text=f"{title} {situacao_key}",
                    confidence_score=0.65,
                    open_date=parse_date_text(_iso_date(item.get("vigenciaInicio")))
                    or parse_date_text(_iso_date(item.get("dataDePublicacao"))),
                    close_date=parse_date_text(_iso_date(item.get("prazoProposto")))
                    or parse_date_text(_iso_date(item.get("vigenciaFim"))),
                    categories=list(self._default_categories),
                    topics=["finep-brasil"],
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
