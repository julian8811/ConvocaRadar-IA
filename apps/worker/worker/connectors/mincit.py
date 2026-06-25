from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urljoin

from worker.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from worker.connectors.common import clean_text, fetch_httpx_text, parse_date_text


MINCIT_PORTAL_BASE = "https://convocatoriasturismo.mincit.gov.co"
MINCIT_LISTING_PATHS = ("/listado-convocatorias/7", "/listado-convocatorias/19", "/listado-convocatorias/1")


class MincitConvocatoriasConnector:
    source_key = "mincit-innovacion"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or f"{MINCIT_PORTAL_BASE}/listado-convocatorias"

    async def fetch(self) -> RawSourceResult:
        chunks: list[str] = []
        final_url = self.base_url
        for path in MINCIT_LISTING_PATHS:
            page_url = urljoin(MINCIT_PORTAL_BASE, path)
            final_url, content, _ = await fetch_httpx_text(
                page_url,
                fallback_content_type="text/html",
                playwright_fallback=False,
            )
            chunks.append(content)
        combined = "\n<!-- page-break -->\n".join(chunks)
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=combined,
            content_type="text/html",
            metadata={"listing_paths": list(MINCIT_LISTING_PATHS)},
        )

    def _parse_blocks(self, html: str) -> list[OpportunityCandidate]:
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()
        for id_match in re.finditer(r"/convocatoria/(\d+)", html):
            convocatoria_id = id_match.group(1)
            official_url = f"{MINCIT_PORTAL_BASE}/convocatoria/{convocatoria_id}"
            if official_url in seen:
                continue
            window = html[max(0, id_match.start() - 1200) : id_match.end() + 200]
            title_match = re.search(r"<h[234][^>]*>([^<]+)</h", window)
            deadline_match = re.search(r"Abierta hasta:\s*([^<\"]+)", window)
            if not title_match:
                continue
            title = clean_text(title_match.group(1))
            if not title or title.lower().startswith("otras convocatorias"):
                continue
            close_date = parse_date_text(deadline_match.group(1).strip()) if deadline_match else None
            if close_date and close_date.date() < datetime.now(UTC).date():
                continue
            seen.add(official_url)
            summary = title
            if close_date:
                summary = f"{title}. Abierta hasta {deadline_match.group(1).strip()}."
            candidates.append(
                OpportunityCandidate(
                    title=title[:180],
                    entity="MinCIT Colombia",
                    country="Colombia",
                    official_url=official_url,
                    summary=summary[:700],
                    categories=["convocatorias", "innovacion", "turismo"],
                    topics=["MinCIT", "Colombia"],
                    raw_text=summary[:2500],
                    confidence_score=0.7,
                    close_date=close_date,
                )
            )
        return candidates

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        return self._parse_blocks(raw.content)[:40]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        return ValidationResult(
            ok=bool(candidate.title and "convocatoriasturismo.mincit.gov.co" in candidate.official_url)
        )
