"""ASCUN WordPress is an editorial feed, not a catalogue of active grants.

Fetch targeted title-search samples across call/education/funding terms, then
rank candidate announcements ahead of retrospective articles. The title gate
provides triage only: deadline/status still require source verification.
"""

from __future__ import annotations

import asyncio
import html
import json
import re
import unicodedata

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import clean_text, is_allowed_host, thin_fill_candidates
from app.connectors.registry import register
from app.core.http_client import http_client

ASCUN_API_URL = "https://ascun.org.co/wp-json/wp/v2/posts"
ASCUN_ALLOWED_HOSTS = ["ascun.org.co", "www.ascun.org.co"]
TITLE_QUERIES = (
    "convocatoria", "beca", "premio", "concurso",
    "inscribirse", "inscríbete", "financiación", "postulaciones",
)
PAGE_SIZE = 30
MAX_PAGES_PER_QUERY = 2
FETCH_CONCURRENCY = 3
PARSE_CANDIDATE_CAP = 200


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    return "".join(c for c in value if not unicodedata.combining(c)).lower()


def _plain(value: object) -> str:
    """Remove HTML from WP rendered excerpts/titles (never parse tags as dates)."""
    if isinstance(value, dict):
        value = value.get("rendered", "")
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]*>", " ", text)
    return clean_text(html.unescape(text))


def _title_decision(title: str) -> tuple[bool, str]:
    """High-precision editorial triage; unknown status is never called open."""
    text = _fold(title)
    # The employment notice and the adjudication/recap are not fresh funding.
    if re.search(
        r"\b(convocatoria\s+(?:profesoral|docente|laboral)|vacantes?|"
        r"oferta\s+laboral|contratacion\s+docente|plazas?\s+docentes?)\b",
        text,
    ):
        return False, "Employment posting, outside funding opportunities"
    if re.search(
        r"\b(ganaron|ganadores?|ganadoras?|gano|ganan|recibio|"
        r"seleccionad[oa]s?|seleccion(?:aron|o)?|premiad[oa]s?|"
        r"se\s+llevo|otorgaron|se\s+otorgaron|entregaron|"
        r"se\s+cerro|cerrada|finalizo|finalizaron)\b",
        text,
    ):
        return False, "Retrospective: awards/selections/results already occurred"
    if re.search(
        r"\b(se\s+preparan\s+para\s+las?\s+convocatorias?|"
        r"se\s+prepara\s+para\s+las?\s+convocatorias?)\b",
        text,
    ):
        return False, "General outlook, not an actionable call"

    # Explicit CTA can make scholarship offers actionable without the token
    # "convocatoria" (e.g. "Inscríbete a la Beca Alberto Assa").
    if re.search(
        r"\b(inscribete|inscribirse|inscripciones?|postulate|postularse|"
        r"postulaciones?|postulacion|aplica|aplicar|"
        r"abre|abierta|abierto|abren|abrieron|lanzan|lanza|"
        r"convocatorias?|concursos?|certamen(?:es)?|"
        r"extiende|amplia|vence\s+plazo|mas\s+plazo)\b",
        text,
    ):
        return True, "Call or application action in title"
    if re.search(
        r"\b(ofrece|ofrecen|disponibles|habilita|habilitan)\b.{0,90}"
        r"\b(becas?|subvenciones?|premios?|financiacion|cupos?)\b",
        text,
    ):
        return True, "Offer with application-like signal"
    return False, "Needs review: no explicit open call or application action in title"


def _categories_for_title(title: str) -> list[str]:
    text = _fold(title)
    if re.search(r"\bbecas?\b", text):
        return ["convocatorias", "becas", "educacion"]
    if re.search(r"\b(premios?|concursos?|certamen(?:es)?)\b", text):
        return ["convocatorias", "premios", "educacion"]
    if re.search(r"\b(fondos?|financiacion|subvenciones?)\b", text):
        return ["convocatorias", "financiacion"]
    return ["convocatorias", "educacion"]


def _published_sort_key(item: dict[str, object]) -> str:
    """Sort by WP publication date for relevance only, never call opening."""
    return str(item.get("date") or "")


@register("ascun-convocatorias")
class AscunConnector:
    source_key = "ascun-convocatorias"

    def __init__(self, base_url: str | None = None, **kwargs) -> None:
        self.base_url = base_url or ASCUN_API_URL

    async def fetch(self) -> RawSourceResult:
        """Bounded title-only multi-search; no database calls or browser."""
        client = await http_client()
        gate = asyncio.Semaphore(FETCH_CONCURRENCY)
        unique: dict[str, dict[str, object]] = {}
        errors: list[str] = []
        query_totals: dict[str, int] = {}
        successes = 0

        async def page(query: str, number: int):
            params = {
                "search": query,
                "search_columns[]": "post_title",
                "per_page": PAGE_SIZE,
                "page": number,
                "_fields": "id,title,excerpt,content,date,link,status",
            }
            async with gate:
                response = await client.get(
                    self.base_url, params=params, timeout=15.0,
                    follow_redirects=True,
                )
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, list):
                    raise ValueError("ASCUN WP returned a non-list payload")
                pages = int(response.headers.get("X-WP-TotalPages", "1") or "1")
                return data, pages

        async def consume(query: str):
            nonlocal successes
            try:
                first, pages = await page(query, 1)
            except Exception as exc:
                errors.append(f"{query}: {type(exc).__name__}")
                return
            successes += 1
            query_totals[query] = len(first)
            batches = [first]
            # At most 2 pages/query, last result is a bounded sample.
            if pages > 1 and MAX_PAGES_PER_QUERY > 1:
                try:
                    second, _ = await page(query, 2)
                    batches.append(second)
                    query_totals[query] += len(second)
                except Exception as exc:
                    errors.append(f"{query}/p2: {type(exc).__name__}")
            for batch in batches:
                for item in batch:
                    if not isinstance(item, dict):
                        continue
                    link = str(item.get("link") or "").strip()
                    if link and link not in unique:
                        unique[link] = item

        await asyncio.gather(*(consume(query) for query in TITLE_QUERIES))
        if not successes:
            raise RuntimeError("All ASCUN WordPress searches failed")

        # Sorting occurs before the parse cap: a recap must not displace an
        # actionable notice merely because one search happened to finish first.
        ordered = sorted(
            unique.values(),
            key=lambda item: (
                int(_title_decision(_plain(item.get("title")))[0]),
                _published_sort_key(item),
            ),
            reverse=True,
        )
        return RawSourceResult(
            source_key=self.source_key,
            url=self.base_url,
            content=json.dumps(ordered, ensure_ascii=False),
            content_type="application/json",
            metadata={
                "searches_ok": successes,
                "searches_total": len(TITLE_QUERIES),
                "unique_posts": len(unique),
                "query_counts": query_totals,
                "search_errors": errors[:8],
                "title_search_only": True,
                "max_pages_per_query": MAX_PAGES_PER_QUERY,
            },
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
            if not isinstance(item, dict) or item.get("status", "publish") != "publish":
                continue
            title = _plain(item.get("title"))
            link = str(item.get("link") or "").strip()
            if not title or not link or link in seen:
                continue
            seen.add(link)
            summary = _plain(item.get("excerpt"))
            body = _plain(item.get("content"))
            summary = summary or body or title
            # WP publication date is NOT opening date. Historical content is
            # still classified, but it cannot be labelled 'open' from WP date.
            candidates.append(
                OpportunityCandidate(
                    title=title[:180],
                    entity="ASCUN Colombia",
                    country="Colombia",
                    official_url=link,
                    summary=summary[:700],
                    categories=_categories_for_title(title),
                    topics=["ascun-convocatorias"],
                    raw_text=(body or summary)[:2500],
                    confidence_score=0.55,
                    open_date=None,
                    close_date=None,
                )
            )
            if len(candidates) >= PARSE_CANDIDATE_CAP:
                break
        return thin_fill_candidates(candidates)

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or URL")
        if not is_allowed_host(candidate.official_url, ASCUN_ALLOWED_HOSTS):
            return ValidationResult(ok=False, reason="URL outside ASCUN allowed domains")
        accepted, reason = _title_decision(candidate.title)
        if not accepted:
            return ValidationResult(ok=False, reason=reason)
        # This only means "candidate for verification", not "currently open".
        return ValidationResult(ok=True)
