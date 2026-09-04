"""Closed convocatorias must not be classified or listed as open.

Two independent failure modes:
1. ``inferred_opportunity_status`` upgrades unknown → open when page chrome
   contains "abierta"/"open", even if the item itself says it is closed.
2. ``build_opportunity_query(status='open')`` filters only the stored status
   column, so rows whose deadline already passed still appear under Abiertas.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.connectors.common import looks_closed_text
from app.services.opportunity import inferred_opportunity_status, opportunity_status
from app.services.search import build_opportunity_query


def test_looks_closed_text_detects_spanish_status() -> None:
    assert looks_closed_text("Convocatoria cerrada")
    assert looks_closed_text("Estado: Finalizada")
    assert looks_closed_text("Esta convocatoria está vencida")
    assert looks_closed_text("Applications closed")
    assert looks_closed_text("This call is closed")


def test_looks_closed_text_does_not_match_cierre_date_label() -> None:
    """'Fecha de cierre' is a deadline label, not a closed status."""
    assert not looks_closed_text("Fecha de cierre: 30 de septiembre de 2026")
    assert not looks_closed_text("Cierre: 14 de agosto, 2027 - 13:00")
    assert not looks_closed_text("Convocatoria abierta para proyectos de innovación")


def test_inferred_closed_from_text_without_close_date() -> None:
    assert inferred_opportunity_status(None, "Convocatoria cerrada") == "closed"
    assert inferred_opportunity_status(None, "Call closed. Not accepting applications") == "closed"


def test_inferred_closed_wins_over_nav_abierta() -> None:
    chrome = (
        "Menú: Convocatorias abiertas. Ver convocatorias abiertas. "
        "Estado: Cerrada. Esta convocatoria ya no está disponible."
    )
    assert inferred_opportunity_status(None, chrome) == "closed"


def test_inferred_open_from_explicit_open_phrase_without_closed() -> None:
    assert inferred_opportunity_status(None, "This opportunity is open for") == "open"


def test_past_close_date_is_closed_even_if_text_says_abierta() -> None:
    past = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=10)
    assert opportunity_status(past) == "closed"
    assert inferred_opportunity_status(past, "Convocatorias abiertas") == "closed"


def test_bancoldex_march_2026_deadline_is_closed() -> None:
    """Source table still says Abierto; the 31 Mar 2026 deadline has passed."""
    close = datetime(2026, 3, 31)
    text = (
        "202603001 El Banco de Comercio Exterior de Colombia S.A.- Bancóldex "
        "24 de Marzo de 2026 31 de Marzo de 2026 Abierto"
    )
    assert opportunity_status(close) == "closed"
    assert inferred_opportunity_status(close, text) == "closed"


def test_opportunity_read_overrides_stale_open_status() -> None:
    from app.schemas.opportunity import OpportunityRead

    now = datetime(2026, 8, 31, 12, 0, 0)
    item = OpportunityRead.model_validate(
        {
            "id": "opp-bancoldex",
            "organization_id": None,
            "slug": "bancoldex-bonos",
            "title": "El Banco de Comercio Exterior de Colombia S.A.- Bancóldex",
            "entity": "Bancóldex",
            "country": "Colombia",
            "status": "open",
            "close_date": datetime(2026, 3, 31),
            "summary": "24 de Marzo de 2026 31 de Marzo de 2026 Abierto Documento TDR",
            "user_status": "review",
            "is_favorite": False,
            "first_seen_at": now,
            "last_seen_at": now,
            "created_at": now,
        }
    )
    assert item.status == "closed"


def test_open_status_filter_excludes_past_close_dates() -> None:
    stmt = build_opportunity_query("org-1", status="open")
    sql = str(stmt.compile(compile_kwargs={"literal_binds": False})).lower()
    assert "status" in sql
    assert "close_date" in sql


def test_closed_status_filter_includes_past_close_dates() -> None:
    stmt = build_opportunity_query("org-1", status="closed")
    compiled = stmt.compile()
    assert "close_date" in str(compiled).lower()


@pytest.mark.asyncio
async def test_generic_validate_still_rejects_closed_for_soft_pass() -> None:
    """Parse may emit closed rows; validate must still signal closed for soft-pass."""
    from app.connectors.base import OpportunityCandidate
    from app.connectors.generic_html import GenericHtmlConnector

    candidate = OpportunityCandidate(
        title="Convocatoria de innovación cerrada",
        entity="Test",
        country="Colombia",
        official_url="https://example.gov.co/cerrada",
        summary="Estado: Cerrada. Ya no acepta postulaciones.",
        raw_text="Estado: Cerrada. Ya no acepta postulaciones.",
        confidence_score=0.7,
        close_date=datetime(2024, 1, 15),
    )
    result = await GenericHtmlConnector("test", "https://example.gov.co").validate(candidate)
    assert result.ok is False
    reason = (result.reason or "").lower()
    assert "closed" in reason or "cerrad" in reason


@pytest.mark.asyncio
async def test_configurable_validate_still_rejects_closed_for_soft_pass() -> None:
    from app.connectors.base import OpportunityCandidate
    from app.connectors.configurable_html import ConfigurableHtmlConnector

    candidate = OpportunityCandidate(
        title="Grant Closed Call",
        entity="Test",
        country="Colombia",
        official_url="https://example.gov.co/closed",
        summary="Applications closed",
        raw_text="Applications closed",
        confidence_score=0.6,
        close_date=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=5),
    )
    connector = ConfigurableHtmlConnector(
        "test",
        "https://example.gov.co",
        {
            "list_selectors": [".card"],
            "title_selectors": ["h2 a"],
            "link_selectors": ["a[href]"],
            "content_selectors": [".content"],
            "date_labels": ["Cierre:"],
        },
    )
    result = await connector.validate(candidate)
    assert result.ok is False
    reason = (result.reason or "").lower()
    assert "closed" in reason or "cerrad" in reason


def test_reconcile_deadline_status_owns_closed_badge() -> None:
    """UI closed badge remains owned by reconcile, not parse drop."""
    from app.schemas.opportunity import OpportunityRead

    now = datetime(2026, 9, 3, 12, 0, 0)
    item = OpportunityRead.model_validate(
        {
            "id": "opp-closed-emit",
            "organization_id": None,
            "slug": "closed-emit",
            "title": "Convocatoria emitida cerrada",
            "entity": "Minciencias",
            "country": "Colombia",
            "status": "open",
            "close_date": datetime(2024, 6, 1),
            "summary": "Estado: Cerrada",
            "user_status": "review",
            "is_favorite": False,
            "first_seen_at": now,
            "last_seen_at": now,
            "created_at": now,
        }
    )
    assert item.status == "closed"
