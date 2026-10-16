"""Fundacion Biodiversidad dedicated connector — expansion 041 X4 (issue #62).

Experimental y REVERSIBLE: este modulo NO se auto-registra (sin ``@register``)
y ``factory.py`` no lo importa, por lo que ``connector_for()`` sigue
devolviendo ``ConfigurableHtmlConnector`` para la key (pines X3 intactos).
Parse probado offline contra el fixture versionado en
``docs/expansion-catalogo-041/piloto-041/fixture-fundacion-biodiversidad.html``
(reconstruido desde lo documentado, SIN fetch real).

Filtros: vencidas (``close_date`` pasado → descartada en parse y rechazada en
``validate``) + pertinencia (anti empleo/noticias) + relevancia (tokens de
convocatorias/ayudas). Cierre desconocido: NUNCA se publica como abierto —
el parse emite la card con ``close_date`` None + marca explicita ``unknown``
(topic ``close-date-unknown`` + nota en summary) y ``validate`` la rechaza
(con razon sin "closed"/"cerrad" para que el runner no le haga soft-pass a
publicado). Dedup intra-pagina por URL normalizada Y por oportunidad
(titulo normalizado + organismo + fecha); la dedup contra el catalogo 203
vive en tests. Elegibilidad geografica ES/UE documentada como
restriccion (ver matriz X1), no como filtro de parse.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import (
    clean_text,
    extract_close_date,
    fetch_httpx_text,
    thin_fill_candidates,
)

SOURCE_KEY = "fundacion-biodiversidad-convocatorias"
BASE_URL = "https://fundacion-biodiversidad.es/buscador-de-convocatorias/"
ENTITY = "Fundacion Biodiversidad F.S.P. (MITECO)"
COUNTRY = "Spain"
ALLOWED_DOMAINS = ("fundacion-biodiversidad.es",)

# Ruido documentado en X3 (empleo + editorial). Coincidencia por subcadena,
# insensible a mayusculas, sobre "titulo + url".
NOISE_KEYWORDS = (
    "empleo",
    "empleos",
    "job",
    "jobs",
    "hiring",
    "vacancy",
    "vacancies",
    "vacante",
    "vacantes",
    "oferta laboral",
    "bolsa de trabajo",
    "oferta de empleo",
    "noticia",
    "noticias",
    "news",
    "press release",
    "nota de prensa",
    "blog post",
    "memoria anual",
)

# El buscador mezcla convocatorias con contenido institucional: solo pasa lo
# que huela a convocatoria financiable.
RELEVANCE_TOKENS = (
    "convocatoria",
    "convocatorias",
    "proyecto",
    "proyectos",
    "ayuda",
    "ayudas",
    "subvencion",
    "subvención",
    "call",
    "proposal",
    "grant",
    "beca",
    "becas",
)


def is_noise(title: str, url: str) -> bool:
    blob = f"{title} {url}".lower()
    return any(keyword in blob for keyword in NOISE_KEYWORDS)


def is_relevant(title: str, url: str) -> bool:
    blob = f"{title} {url}".lower()
    return any(token in blob for token in RELEVANCE_TOKENS)


def normalize_url(url: str) -> tuple[str, str]:
    """(host, path) minusculas sin barra final — pin de dedup semantica."""
    parsed = urlparse(url)
    return (parsed.netloc.lower(), parsed.path.rstrip("/").lower())


def title_key(title: str) -> str:
    """Titulo colapsado a alfanumericos — pin de dedup semantica."""
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


# Cierre desconocido: estado explicito unknown/sin-fecha. El texto NO afirma
# vigencia ("abierta"/"open") en ningun caso: sin evidencia de fecha no hay
# evidencia de apertura.
CLOSE_DATE_UNKNOWN_TOPIC = "close-date-unknown"
UNKNOWN_CLOSE_NOTE = (
    "[Cierre desconocido / close date unknown — "
    "verificar vigencia en la pagina oficial]"
)


def opp_key(title: str, entity: str, close_date: datetime | None) -> tuple[str, str, str]:
    """Llave de oportunidad: titulo normalizado + organismo + fecha ISO (o
    ``"unknown"`` sin fecha). Dedup por oportunidad, no solo por URL: la
    misma convocatoria republicada bajo otro path colapsa igual."""
    date_part = close_date.date().isoformat() if close_date else "unknown"
    return (title_key(title), entity.strip().lower(), date_part)


def mark_close_unknown(candidate: OpportunityCandidate) -> OpportunityCandidate:
    """Estampa estado unknown/sin-fecha sobre un candidato sin cierre."""
    if CLOSE_DATE_UNKNOWN_TOPIC not in (candidate.topics or []):
        candidate.topics = [*(candidate.topics or []), CLOSE_DATE_UNKNOWN_TOPIC]
    if "unknown" not in (candidate.summary or "").lower():
        candidate.summary = f"{UNKNOWN_CLOSE_NOTE} {candidate.summary or candidate.title}"
    return candidate


def is_expired(close_date: datetime | None) -> bool:
    return bool(close_date and close_date.date() < datetime.now(UTC).date())


def _block_text(anchor) -> str:
    """Texto del bloque tarjeta: sube hasta el `article` ancestro (la fecha
    vive en el `p` hermano del `h2`, no en el anchor)."""
    node = anchor
    for _ in range(4):
        node = node.parent
        if node is None:
            break
        if (getattr(node, "tag", "") or "") == "article":
            text = clean_text(node.text())
            if text:
                return text
    parent = anchor.parent
    return clean_text(parent.text()) if parent is not None else ""


class FundacionBiodiversidadConnector:
    """Conector dedicado Fundacion Biodiversidad. Ver docstring del modulo."""

    source_key = SOURCE_KEY
    BASE_URL = BASE_URL

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or BASE_URL

    @staticmethod
    def normalize_url(url: str) -> tuple[str, str]:
        return normalize_url(url)

    @staticmethod
    def title_key(title: str) -> str:
        return title_key(title)

    @staticmethod
    def opp_key(title: str, entity: str, close_date: datetime | None) -> tuple[str, str, str]:
        return opp_key(title, entity, close_date)

    async def fetch(self) -> RawSourceResult:
        final_url, content, content_type = await fetch_httpx_text(
            self.base_url,
            fallback_content_type="text/html",
        )
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=content,
            content_type=content_type,
        )

    def parse_html(self, html: str, page_url: str) -> list[OpportunityCandidate]:
        """Parse sincronico y testeable: anchors same-host con pertinencia,
        relevancia y filtro de vencidas. Sin fecha de cierre la card se emite
        marcada unknown (jamas como abierta); dedup por URL y por oportunidad."""
        tree = HTMLParser(html)
        candidates: list[OpportunityCandidate] = []
        seen_urls: set[tuple[str, str]] = set()
        seen_opp: set[tuple[str, str, str]] = set()
        for anchor in tree.css("main a[href], article a[href]"):
            href = (anchor.attributes.get("href") or "").strip()
            if not href or href.startswith(("#", "mailto:", "javascript:")):
                continue
            link = urljoin(page_url, href)
            if urlparse(link).netloc.lower() not in ALLOWED_DOMAINS:
                continue
            title = clean_text(anchor.text()) or ""
            if len(title) < 8:
                continue
            if is_noise(title, link) or not is_relevant(title, link):
                continue
            norm = normalize_url(link)
            if norm in seen_urls:
                continue
            seen_urls.add(norm)
            text = _block_text(anchor) or title
            close_date = extract_close_date(text)
            if is_expired(close_date):
                continue
            key = opp_key(title, ENTITY, close_date)
            if key in seen_opp:
                continue
            seen_opp.add(key)
            summary = text[:700] or title
            candidates.append(
                OpportunityCandidate(
                    title=title[:180],
                    entity=ENTITY,
                    country=COUNTRY,
                    official_url=link,
                    summary=summary,
                    categories=["grants", "biodiversity", "environment", "subvenciones"],
                    raw_text=text[:2500],
                    confidence_score=0.7,
                    close_date=close_date,
                )
            )
        filled = thin_fill_candidates(candidates[:50])
        return [
            mark_close_unknown(cand) if cand.close_date is None else cand
            for cand in filled
        ]

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        return self.parse_html(raw.content, raw.url)

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        if not candidate.title or not candidate.official_url:
            return ValidationResult(ok=False, reason="Missing title or URL")
        if candidate.close_date is None:
            # Sin evidencia de vigencia no hay apertura: se rechaza (y la
            # razon evita "closed"/"cerrad" para que el runner no le haga
            # soft-pass a publicado).
            return ValidationResult(
                ok=False,
                reason="Close date unknown — cannot confirm open; verify on the official page",
            )
        if is_expired(candidate.close_date):
            return ValidationResult(ok=False, reason="Opportunity expired (close_date past)")
        if is_noise(candidate.title, candidate.official_url):
            return ValidationResult(ok=False, reason="Looks like employment/news noise")
        return ValidationResult(ok=True)
