"""Tests: every OpportunityCandidate field must survive the trip to OpportunityCreate.

The DB model and ``OpportunityCreate`` have always carried rich columns
(application_url, eligible_applicants, documents_required, evaluation_criteria,
restrictions, funding value/currency, region, description). The scraper
contract did not, so connectors had no way to express them and those columns
stayed empty for every row. These tests pin the contract end to end.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.scraper.runner import _scrape_candidates

OPEN = datetime(2026, 3, 1)
CLOSE = datetime(2026, 9, 30)


class _RichConnector:
    """Connector that fills every field the candidate contract exposes."""

    source_key = "rich-source"

    async def fetch(self) -> RawSourceResult:
        return RawSourceResult(
            source_key=self.source_key,
            url="https://example.gov.co/convocatoria",
            content="<html><body>contenido</body></html>",
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        return [
            OpportunityCandidate(
                title="Convocatoria de innovación 2026",
                entity="Minciencias",
                country="Colombia",
                official_url="https://example.gov.co/convocatoria",
                application_url="https://example.gov.co/postular",
                language="es",
                summary="Convocatoria para proyectos de innovación con enfoque regional.",
                description="Descripción larga e independiente del resumen.",
                categories=["innovacion"],
                topics=["ctei"],
                eligible_applicants=["Empresas colombianas", "Centros de investigación"],
                requirements=["Estar constituida legalmente"],
                documents_required=["Certificado de existencia"],
                evaluation_criteria=["Pertinencia técnica", "Impacto regional"],
                restrictions=["No podrán participar entidades sancionadas"],
                region="Andina",
                raw_text="x" * 400,
                confidence_score=0.9,
                open_date=OPEN,
                close_date=CLOSE,
                funding_amount_raw="hasta 500 millones de pesos",
                funding_amount_value=500_000_000.0,
                funding_amount_currency="COP",
            )
        ]

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        return ValidationResult(ok=True)


class _Source:
    id = "src-1"
    key = "rich-source"
    name = "Rich Source"
    base_url = "https://example.gov.co"
    source_type = "html"
    country = "Colombia"
    category: list[str] = []
    region = "Fallback Region"
    connector_config = None


@pytest.fixture()
def scraped(monkeypatch):
    monkeypatch.setattr(
        "app.connectors.factory.connector_for",
        lambda *args, **kwargs: _RichConnector(),
    )
    return _Source()


async def _run(source) -> object:
    items = await _scrape_candidates(source)
    assert len(items) == 1, "the rich candidate must survive noise/validation filters"
    return items[0]


async def test_candidate_exposes_rich_fields():
    """The dataclass itself must accept the rich fields."""
    candidate = OpportunityCandidate(
        title="t",
        entity="e",
        country="Colombia",
        official_url="https://example.gov.co/x",
        application_url="https://example.gov.co/apply",
        eligible_applicants=["a"],
        documents_required=["d"],
        evaluation_criteria=["c"],
        restrictions=["r"],
        region="Andina",
        description="desc",
        funding_amount_value=1000.0,
        funding_amount_currency="COP",
    )
    assert candidate.application_url == "https://example.gov.co/apply"
    assert candidate.eligible_applicants == ["a"]
    assert candidate.documents_required == ["d"]
    assert candidate.evaluation_criteria == ["c"]
    assert candidate.restrictions == ["r"]
    assert candidate.region == "Andina"
    assert candidate.description == "desc"
    assert candidate.funding_amount_value == 1000.0
    assert candidate.funding_amount_currency == "COP"


async def test_application_url_reaches_opportunity_create(scraped):
    item = await _run(scraped)
    assert item.application_url == "https://example.gov.co/postular"


async def test_narrative_lists_reach_opportunity_create(scraped):
    item = await _run(scraped)
    assert item.eligible_applicants == ["Empresas colombianas", "Centros de investigación"]
    assert item.documents_required == ["Certificado de existencia"]
    assert item.evaluation_criteria == ["Pertinencia técnica", "Impacto regional"]
    assert item.restrictions == ["No podrán participar entidades sancionadas"]
    assert item.requirements == ["Estar constituida legalmente"]


async def test_funding_value_and_currency_reach_opportunity_create(scraped):
    item = await _run(scraped)
    assert item.funding_amount_raw == "hasta 500 millones de pesos"
    assert item.funding_amount_value == 500_000_000.0
    assert item.funding_amount_currency == "COP"


async def test_dates_reach_opportunity_create(scraped):
    item = await _run(scraped)
    assert item.open_date == OPEN
    assert item.close_date == CLOSE


async def test_candidate_description_is_not_overwritten_by_summary(scraped):
    """description must stay independent instead of being a copy of summary."""
    item = await _run(scraped)
    assert item.description == "Descripción larga e independiente del resumen."
    assert item.summary == "Convocatoria para proyectos de innovación con enfoque regional."


async def test_candidate_region_wins_over_source_region(scraped):
    """A region scraped from the page is more specific than the source default."""
    item = await _run(scraped)
    assert item.region == "Andina"


async def test_runner_fills_dates_and_funding_from_list_card_text(monkeypatch):
    """Specialized connectors that only set title/summary still get mapped fields."""

    class _ThinConnector(_RichConnector):
        async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
            text = (
                "Convocatoria de innovación 2026. "
                "Apertura: 15 de marzo de 2026. "
                "Fecha de cierre: 30 de septiembre de 2026. "
                "Monto: hasta 500 millones de pesos colombianos."
            )
            return [
                OpportunityCandidate(
                    title="Convocatoria de innovación 2026",
                    entity="Minciencias",
                    country="Colombia",
                    official_url="https://example.gov.co/convocatoria",
                    summary=text,
                    raw_text=text,
                    confidence_score=0.6,
                )
            ]

    monkeypatch.setattr(
        "app.connectors.factory.connector_for",
        lambda *args, **kwargs: _ThinConnector(),
    )
    item = await _run(_Source())
    assert item.close_date is not None
    assert item.close_date.year == 2026
    assert item.close_date.month == 9
    assert item.funding_amount_raw
    assert "500" in item.funding_amount_raw


async def test_runner_persists_candidate_rejected_as_closed(monkeypatch):
    """Closed items must be stored as closed, not dropped at validation."""

    class _ClosedConnector(_RichConnector):
        async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
            return [
                OpportunityCandidate(
                    title="Convocatoria cerrada 2024",
                    entity="Minciencias",
                    country="Colombia",
                    official_url="https://example.gov.co/cerrada",
                    summary="Estado: Cerrada. Ya no está disponible.",
                    raw_text="Estado: Cerrada. Ya no está disponible.",
                    confidence_score=0.7,
                    close_date=datetime(2024, 1, 15),
                )
            ]

        async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
            return ValidationResult(ok=False, reason="Opportunity appears closed")

    monkeypatch.setattr(
        "app.connectors.factory.connector_for",
        lambda *args, **kwargs: _ClosedConnector(),
    )
    items = await _scrape_candidates(_Source())
    assert len(items) == 1
    assert items[0].title == "Convocatoria cerrada 2024"
    assert items[0].close_date == datetime(2024, 1, 15)


async def test_source_region_used_when_candidate_has_none(monkeypatch):
    class _PlainConnector(_RichConnector):
        async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
            return [
                OpportunityCandidate(
                    title="Convocatoria sin región",
                    entity="Minciencias",
                    country="Colombia",
                    official_url="https://example.gov.co/otra",
                    summary="Resumen suficientemente descriptivo de la convocatoria.",
                    raw_text="y" * 400,
                )
            ]

    monkeypatch.setattr(
        "app.connectors.factory.connector_for",
        lambda *args, **kwargs: _PlainConnector(),
    )
    item = await _run(_Source())
    assert item.region == "Fallback Region"
