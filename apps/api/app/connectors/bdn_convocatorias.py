from app.connectors.registry import register
from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from app.connectors.common import fetch_httpx_text, parse_date_text
from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult


BDN_API_URL = "https://www.infosubvenciones.es/bdnstrans/api/convocatorias/busqueda"
BDN_DETAIL_URL = "https://www.infosubvenciones.es/bdnstrans/GE/es/convocatorias/{item_id}"


@register("cdti-convocatorias")
@register("isciii-convocatorias")
class BdnConvocatoriasConnector:
    def __init__(
        self,
        source_key: str,
        base_url: str,
        *,
        search_query: str,
        entity_name: str,
        default_country: str = "Spain",
        allowed_domains: list[str] | None = None,
    ) -> None:
        self.source_key = source_key
        self.base_url = base_url or BDN_API_URL
        self.search_query = search_query
        self.entity_name = entity_name
        self.default_country = default_country
        self.allowed_domains = allowed_domains or ["infosubvenciones.es", "www.infosubvenciones.es"]

    def _page_url(self, page: int, *, per_page: int = 50) -> str:
        parsed = urlparse(self.base_url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        query["pagina"] = [str(page)]
        query["resultadosPorPagina"] = [str(per_page)]
        query["descripcion"] = [self.search_query]
        return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))

    async def fetch(self) -> RawSourceResult:
        all_items: list[dict[str, object]] = []
        final_url = self._page_url(1)
        total_pages = 1
        for page in range(1, 11):
            page_url = self._page_url(page)
            final_url, content, _ = await fetch_httpx_text(
                page_url,
                fallback_content_type="application/json",
                playwright_fallback=False,
            )
            payload = json.loads(content)
            items = payload.get("content") or []
            if page == 1:
                total_pages = int(payload.get("totalPages") or 1)
            if not items:
                break
            all_items.extend(item for item in items if isinstance(item, dict))
            if page >= total_pages:
                break
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=json.dumps(all_items, ensure_ascii=False),
            content_type="application/json",
            metadata={"search_query": self.search_query, "items_fetched": len(all_items)},
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        try:
            items = json.loads(raw.content)
        except json.JSONDecodeError:
            return []
        if not isinstance(items, list):
            return []
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("descripcion") or item.get("descripcionLeng") or "").strip()
            item_id = str(item.get("id") or item.get("numeroConvocatoria") or "").strip()
            if not title or not item_id or item_id in seen:
                continue
            lowered = title.lower()
            if any(token in lowered for token in ("anulación", "anulacion", "rectificación", "rectificacion", "modificación", "modificacion")):
                continue
            seen.add(item_id)
            open_date = parse_date_text(str(item.get("fechaRecepcion") or ""))
            close_date = parse_date_text(str(item.get("fechaFinSolicitud") or ""))
            official_url = BDN_DETAIL_URL.format(item_id=item_id)
            organ = str(item.get("nivel3") or item.get("nivel2") or self.entity_name).strip()
            candidates.append(
                OpportunityCandidate(
                    title=title[:180],
                    entity=organ or self.entity_name,
                    country=self.default_country,
                    official_url=official_url,
                    summary=title[:700],
                    categories=["convocatorias", "grants", "research"],
                    topics=[self.entity_name],
                    raw_text=title[:2500],
                    confidence_score=0.74,
                    open_date=open_date,
                    close_date=close_date,
                )
            )
        return candidates[:150]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        return ValidationResult(ok=bool(candidate.title and "infosubvenciones.es" in candidate.official_url))
