"""ASCUN: candidate *calls*, not every university news article in WordPress.

ASCUN's WordPress search is discovery, not proof of an open grant. Keep ambiguous
calls in the normal opportunity pipeline with unknown deadline, and quarantine
obvious news, retrospective prize coverage and faculty employment notices.
"""

from __future__ import annotations

import json
import re
import unicodedata

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import clean_text, fetch_httpx_text, is_allowed_host, thin_fill_candidates
from app.connectors.registry import register

ASCUN_API_URL = "https://ascun.org.co/wp-json/wp/v2/posts"
ASCUN_ALLOWED_HOSTS = ["ascun.org.co", "www.ascun.org.co"]


def _fold(value: str) -> str:
    """Accent-independent, lowercase matching for Spanish editorial titles."""
    lowered = unicodedata.normalize("NFKD", value or "")
    return "".join(c for c in lowered if not unicodedata.combining(c)).lower()


def _is_actionable_title(title: str) -> bool:
    """High-precision title triage, *not* a claim that applications remain open.

    Deliberately abstain on generic press/news (including award winners).
    Retain actual call announcements, including competitions and scholarships.
    """
    title = _fold(title)
    if re.search(
        r"\b(convocatoria\s+(?:profesoral|docente|laboral)|"
        r"vacantes?|oferta\s+laboral|contratacion\s+docente|plazas?\s+docentes?)\b",
        title,
    ):
        return False
    if re.search(
        r"\b(ganaron|ganadores?|ganadoras?|gano|ganan|recibio|obtuvieron|"
        r"fueron\s+seleccionad[oa]s?|resultados\s+de|cerro|cerrada|finalizo)\b",
        title,
    ):
        return False
    if re.search(
        r"\b(convocatorias?|concursos?|certamen(?:es)?|postulaciones?|"
        r"inscripciones?|inscribirse|postularse)\b",
        title,
    ):
        return True
    return bool(
        re.search(
            r"\b(abre|abierta|apertura|lanza|lanzan)\b.{0,70}"
            r"\b(becas?|fondos?|subvenciones?|financiacion|premios?)\b",
            title,
        )
    )


def _categories_for_title(title: str) -> list[str]:
    title = _fold(title)
    if "beca" in title:
        return ["convocatorias", "becas", "educacion"]
    if re.search(r"\b(premio|premios|concurso|concursos|certamen)\b", title):
        return ["convocatorias", "premios", "educacion"]
    if re.search(r"\b(fondo|financiacion|subvencion)\b", title):
        return ["convocatorias", "financiacion"]
    return ["convocatorias", "educacion"]


@register("ascun-convocatorias")
class AscunConnector:
    source_key = "ascun-convocatorias"

    def __init__(self, base_url: str | None = None, **kwargs) -> None:
        self.base_url = base_url or ASCUN_API_URL

    async def fetch(self) -> RawSourceResult:
        # Limit network cost and rely on the WP search only as discovery.
        # "convocatoria" in a body does not imply an actionable opportunity.
        join = "&" if "?" in self.base_url else "?"
        url = (
            f"{self.base_url}{join}"
            "search=convocatoria&per_page=20&_fields=id,title,content,excerpt,date,link"
        )
        final_url, content, content_type = await fetch_httpx_text(
            url,
            fallback_content_type="application/json",
            timeout_seconds=20,
            retries=1,
            playwright_fallback=False,
        )
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=content,
            content_type=content_type,
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        try:
            items = json.loads(raw.content)
        except (json.JSONDecodeError, TypeError):
            return []
        if not isinstance(items, list):
            return []
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            title_field = item.get("title", {})
            title = clean_text(
                title_field.get("rendered", "")
                if isinstance(title_field, dict)
                else str(title_field or "")
            )
            link = str(item.get("link") or "").strip()
            if not title or not link or link in seen:
                continue
            seen.add(link)

            excerpt_field = item.get("excerpt", {})
            content_field = item.get("content", {})
            excerpt = clean_text(
                excerpt_field.get("rendered", "")
                if isinstance(excerpt_field, dict)
                else str(excerpt_field or "")
            )
            full_text = clean_text(
                content_field.get("rendered", "")
                if isinstance(content_field, dict)
                else str(content_field or "")
            )
            summary = excerpt or full_text or title

            # A WordPress publishing date is NOT an application opening date.
            # Likewise, do not invent closing dates from general article prose.
            candidates.append(
                OpportunityCandidate(
                    title=title[:180],
                    entity="ASCUN Colombia",
                    country="Colombia",
                    official_url=link,
                    summary=summary[:700],
                    categories=_categories_for_title(title),
                    topics=["ascun-convocatorias"],
                    raw_text=(full_text or summary)[:2500],
                    confidence_score=0.55,
                    open_date=None,
                    close_date=None,
                )
            )
        return thin_fill_candidates(candidates[:30])

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or URL")
        if not is_allowed_host(candidate.official_url, ASCUN_ALLOWED_HOSTS):
            return ValidationResult(ok=False, reason="URL outside ASCUN allowed domains")
        if not _is_actionable_title(candidate.title):
            return ValidationResult(
                ok=False,
                reason="Editorial article: no actionable call in title or employment news",
            )
        return ValidationResult(ok=True)
