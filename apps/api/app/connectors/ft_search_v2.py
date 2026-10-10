"""Funding & Tenders search-API v2 unified connector (F1 fuentes-cirugia-mayor).

One parametrized connector serves the four EU programme sources
(erc-calls, horizon-europe-sedia, msca-funding, eu-creative-europe-calls).

Transport reuses the verified ``eic_accelerator`` fetch: POST with an empty
body to ``{FT_SEARCH_URL}?apiKey={key}&text={term}&pageSize=50&pageNumber=1``,
with the public ``sedia_api_key`` read from settings (never hardcoded).
Payload shape + date/status parsing reuse the ``horizon_sedia`` v2 logic
(``metadata.callTitle/callIdentifier/identifier/actions/status``,
``_is_openish``). Each programme adds a match predicate so the four sources
stay disjoint (RED2: horizon without a programme filter claimed MSCA items).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import quote_plus

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import fetch_httpx_text, thin_fill_candidates
from app.connectors.registry import register
from app.core.config import get_settings

EU_TOPIC_URL = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/{identifier}"
FT_SEARCH_URL = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
FT_PAGE_SIZE = 50


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _first_text(value: object) -> str | None:
    if isinstance(value, list) and value:
        first = value[0]
        return str(first).strip() if first is not None else None
    if isinstance(value, str):
        return value.strip()
    return None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%d %B %Y"):
        try:
            parsed = datetime.strptime(value.replace("Z", "+0000"), fmt)
        except ValueError:
            continue
        return parsed.astimezone(UTC).replace(tzinfo=None)
    return None


def _parse_action_dates(actions: list[object]) -> tuple[datetime | None, datetime | None]:
    open_date = None
    close_date = None
    for action in actions:
        if isinstance(action, str):
            try:
                parsed = json.loads(action)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, list) and parsed:
                action = parsed[0]
        if not isinstance(action, dict):
            continue
        planned = action.get("plannedOpeningDate")
        deadlines = action.get("deadlineDates") or []
        if planned and not open_date:
            open_date = _parse_date(planned)
        if deadlines:
            close_date = _parse_date(deadlines[-1])
    return open_date, close_date


def _is_openish(status_values: list[str], close_date: datetime | None) -> bool:
    now = datetime.now(UTC).replace(tzinfo=None)
    if close_date and close_date < now:
        return False
    return not status_values or any(value not in {"31094503", "closed"} for value in status_values)


@dataclass(frozen=True)
class ProgramSpec:
    """Per-programme identity: fetch terms, candidate dressing, match predicate."""

    key: str
    terms: tuple[str, ...]
    entity: str
    categories: tuple[str, ...]
    topics_fallback: tuple[str, ...] = ()
    confidence: float = 0.76
    # Match predicate inputs (all case-insensitive):
    id_prefixes: tuple[str, ...] = ()
    word_patterns: tuple[str, ...] = ()
    phrases: tuple[str, ...] = ()
    # When True the programme claims whatever the other three reject
    # (Horizon Europe is the framework programme = catch-all bucket).
    catch_all: bool = False


def _programme_texts(item: dict) -> tuple[str, str]:
    metadata = item.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    identifiers = " ".join(
        str(value)
        for field_name in ("identifier", "callIdentifier")
        for value in (metadata.get(field_name) or [])
        if value is not None
    )
    keywords = " ".join(
        str(value) for value in (metadata.get("keywords") or []) if isinstance(value, str)
    )
    combined = " ".join(
        [
            identifiers,
            _clean(_first_text(metadata.get("callTitle")) or ""),
            _clean(str(item.get("summary") or "")),
            keywords,
        ]
    ).upper()
    return identifiers.upper(), combined


def _matches_program(item: dict, spec: ProgramSpec) -> bool:
    identifiers, combined = _programme_texts(item)
    if any(identifiers.startswith(prefix) for prefix in spec.id_prefixes):
        return True
    if any(re.search(pattern, combined) for pattern in spec.word_patterns):
        return True
    return any(phrase in combined for phrase in spec.phrases)


ERC_PROGRAM = ProgramSpec(
    key="erc-calls",
    terms=(
        "ERC Starting Grant",
        "ERC Consolidator Grant",
        "ERC Advanced Grant",
        "ERC Proof of Concept",
        "European Research Council",
    ),
    entity="European Research Council",
    categories=("grants", "research", "european research council"),
    topics_fallback=("ERC", "horizon europe", "research funding"),
    confidence=0.8,
    id_prefixes=("ERC",),
    word_patterns=(r"\bERC\b",),
    phrases=("EUROPEAN RESEARCH COUNCIL",),
)

MSCA_PROGRAM = ProgramSpec(
    key="msca-funding",
    terms=(
        "MSCA",
        "Marie Skłodowska-Curie",
        "Postdoctoral Fellowships",
        "Doctoral Networks",
        "MSCA Staff Exchanges",
    ),
    entity="Marie Skłodowska-Curie Actions",
    categories=("grants", "fellowships", "research", "msca"),
    topics_fallback=("MSCA", "fellowships", "horizon europe"),
    confidence=0.76,
    id_prefixes=("MSCA", "HORIZON-MSCA"),
    word_patterns=(r"\bMSCA\b",),
    phrases=("MARIE SK", "SKLODOWSKA", "SKŁODOWSKA"),
)

CREATIVE_PROGRAM = ProgramSpec(
    key="eu-creative-europe-calls",
    terms=("Creative Europe", "CREA"),
    entity="Creative Europe",
    categories=("grants", "culture", "creative europe"),
    topics_fallback=("Creative Europe", "culture"),
    confidence=0.76,
    id_prefixes=("CREA",),
    word_patterns=(r"\bCREA\b",),
    phrases=("CREATIVE EUROPE",),
)

HORIZON_PROGRAM = ProgramSpec(
    key="horizon-europe-sedia",
    terms=(
        "Horizon Europe",
        "open call",
        "research and innovation",
        "2026",
        "2027",
    ),
    entity="Horizon Europe",
    categories=("grants", "research", "innovation", "horizon europe"),
    confidence=0.74,
    catch_all=True,
)

FILTERED_PROGRAMS = (ERC_PROGRAM, MSCA_PROGRAM, CREATIVE_PROGRAM)


class FtSearchV2Connector:
    """Shared F&T v2 fetch + parse, parametrized by :attr:`PROGRAM`."""

    source_key = "ft-search-v2"
    PROGRAM: ProgramSpec = HORIZON_PROGRAM

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or FT_SEARCH_URL

    def _claims(self, item: dict) -> bool:
        if self.PROGRAM.catch_all:
            return not any(_matches_program(item, spec) for spec in FILTERED_PROGRAMS)
        return _matches_program(item, self.PROGRAM)

    async def fetch(self) -> RawSourceResult:
        results: list[dict[str, object]] = []
        seen: set[str] = set()
        final_url = self.base_url
        api_key = get_settings().sedia_api_key
        for term in self.PROGRAM.terms:
            search_url = (
                f"{FT_SEARCH_URL}?apiKey={api_key}"
                f"&text={quote_plus(term)}&pageSize={FT_PAGE_SIZE}&pageNumber=1"
            )
            try:
                final_url, content, _ = await fetch_httpx_text(
                    search_url,
                    method="POST",
                    fallback_content_type="application/json",
                )
                decoded = json.loads(content)
            except Exception:
                continue
            for item in decoded.get("results") or []:
                if not isinstance(item, dict):
                    continue
                if not self._claims(item):
                    continue
                metadata = item.get("metadata") or {}
                if not isinstance(metadata, dict):
                    metadata = {}
                identifier = _clean(
                    _first_text(metadata.get("identifier"))
                    or _first_text(metadata.get("callIdentifier"))
                    or str(item.get("reference") or "")
                )
                if not identifier or identifier in seen:
                    continue
                seen.add(identifier)
                results.append(item)
        content = json.dumps({"results": results}, ensure_ascii=False)
        return RawSourceResult(
            source_key=self.source_key,
            url=final_url,
            content=content,
            content_type="application/json",
            metadata={"terms": list(self.PROGRAM.terms), "result_count": len(results)},
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        payload = json.loads(raw.content)
        items = payload.get("results") or []
        candidates: list[OpportunityCandidate] = []
        seen: set[str] = set()
        for item in items:
            if not self._claims(item):
                continue
            metadata = item.get("metadata") or {}
            call_titles = metadata.get("callTitle") or []
            title = _clean(_first_text(call_titles) or item.get("summary") or item.get("content"))
            identifiers = metadata.get("identifier") or []
            call_identifiers = metadata.get("callIdentifier") or []
            identifier = _clean(
                _first_text(identifiers) or _first_text(call_identifiers) or item.get("reference")
            )
            if not title or not identifier or identifier in seen:
                continue
            status_values = [
                str(value) for value in (metadata.get("status") or []) if value is not None
            ]
            open_date, close_date = _parse_action_dates(metadata.get("actions") or [])
            if not open_date:
                open_date = _parse_date(_first_text(metadata.get("startDate")))
            if not close_date:
                close_date = _parse_date(_first_text(metadata.get("deadlineDate")))
            if not _is_openish(status_values, close_date):
                continue
            seen.add(identifier)
            keywords = [
                str(value) for value in (metadata.get("keywords") or []) if isinstance(value, str)
            ]
            candidates.append(
                OpportunityCandidate(
                    title=title[:180],
                    entity=self.PROGRAM.entity,
                    country="European Union",
                    official_url=EU_TOPIC_URL.format(identifier=quote_plus(identifier)),
                    summary=_clean(item.get("summary") or title)[:700],
                    categories=list(self.PROGRAM.categories),
                    topics=keywords[:5] or list(self.PROGRAM.topics_fallback),
                    raw_text=_clean(item.get("content") or title)[:2500],
                    confidence_score=self.PROGRAM.confidence,
                    open_date=open_date,
                    close_date=close_date,
                )
            )
        return thin_fill_candidates(candidates[:80])

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        return ValidationResult(ok=bool(candidate.title and candidate.official_url))


@register("erc-calls")
class ErcV2Connector(FtSearchV2Connector):
    source_key = "erc-calls"
    PROGRAM: ProgramSpec = ERC_PROGRAM


@register("horizon-europe-sedia")
class HorizonV2Connector(FtSearchV2Connector):
    source_key = "horizon-europe-sedia"
    PROGRAM: ProgramSpec = HORIZON_PROGRAM


@register("msca-funding")
class MscaV2Connector(FtSearchV2Connector):
    source_key = "msca-funding"
    PROGRAM: ProgramSpec = MSCA_PROGRAM


@register("eu-creative-europe-calls")
class CreativeEuropeV2Connector(FtSearchV2Connector):
    source_key = "eu-creative-europe-calls"
    PROGRAM: ProgramSpec = CREATIVE_PROGRAM


__all__ = [
    "CREATIVE_PROGRAM",
    "ERC_PROGRAM",
    "FILTERED_PROGRAMS",
    "FT_PAGE_SIZE",
    "FT_SEARCH_URL",
    "HORIZON_PROGRAM",
    "MSCA_PROGRAM",
    "CreativeEuropeV2Connector",
    "ErcV2Connector",
    "FtSearchV2Connector",
    "HorizonV2Connector",
    "MscaV2Connector",
    "ProgramSpec",
]
