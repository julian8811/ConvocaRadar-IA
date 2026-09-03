"""Tests: captura de datos reales para informes.

Cubre el detector de resumenes delgados/metadata, la no-degradacion de
resumenes sustanciales al re-scrapear (_update_opportunity) y el filtro
de ruido del generador de informes.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.models import Opportunity
from app.services.opportunity import (
    OpportunityCreate,
    _update_opportunity,
    is_thin_or_metadata_summary,
)

NOW = datetime.now(UTC).replace(tzinfo=None)


def _make_opp(**kwargs) -> Opportunity:
    defaults = dict(
        title="Convocatoria de prueba",
        slug="convocatoria-de-prueba",
        entity="Entidad",
        country="Colombia",
        categories=[],
        topics=[],
        description="Descripcion base",
        summary="Resumen base",
        raw_text="Texto crudo",
        language="es",
        confidence_score=0.8,
        status="open",
        user_status="none",
    )
    defaults.update(kwargs)
    return Opportunity(**defaults)


def _make_data(summary: str) -> OpportunityCreate:
    return OpportunityCreate(
        title="Convocatoria de prueba",
        entity="Entidad",
        country="Colombia",
        official_url="https://example.gov/opportunity/1",
        summary=summary,
        description="Descripcion entrante",
        raw_text="x" * 150,
        close_date=NOW,
        confidence_score=0.82,
    )


def test_metadata_summary_is_thin():
    assert is_thin_or_metadata_summary("Number: O-COPS-2026-172583 | Agency: Simpler Grants")
    assert is_thin_or_metadata_summary("DFOP0019426 | DOS-DRL | Status: posted")
    assert is_thin_or_metadata_summary("short")
    assert is_thin_or_metadata_summary("")
    assert is_thin_or_metadata_summary(None)
    assert is_thin_or_metadata_summary("sitemap entry — lastmod: 2026-07-21")
    banner = "An official website of the United States government " + "x" * 200
    assert is_thin_or_metadata_summary(banner)
    labels = "Eligible Applicants: Others. Funding Opportunity Title: Something. Category: Other."
    assert is_thin_or_metadata_summary(labels)


def test_substantive_summary_is_not_thin():
    good = (
        "Department of State's Embassy Ottawa announces an open competition to "
        "implement a program to connect U.S. citizen talent with Canadian "
        "audiences and institutions on topics of mutual interest."
    )
    assert not is_thin_or_metadata_summary(good)


def test_rescrape_does_not_downgrade_substantive_summary():
    good = (
        "Department of State's Embassy Ottawa announces an open competition to "
        "implement a program to connect U.S. citizen talent with Canadian "
        "audiences and institutions on topics of mutual interest."
    )
    opp = _make_opp(summary=good)
    junk = _make_data("Number: O-COPS-2026-172583 | Agency: Simpler Grants")
    _update_opportunity(opp, junk, opp.title)
    assert opp.summary == good


def test_rescrape_replaces_thin_with_substantive():
    opp = _make_opp(summary="Number: X | Agency: Y")
    data = _make_data(
        "Embassy Jerusalem's Public Diplomacy Section announces an open "
        "competition to implement projects that advance shared priorities."
    )
    _update_opportunity(opp, data, opp.title)
    assert opp.summary.startswith("Embassy Jerusalem")


def test_report_filter_hides_metadata_summaries():
    from app.services.export import generate_report_html

    class Org:
        name = "Org"

    junk_opp = _make_opp(summary="Number: 12345 | Agency: Simpler Grants")
    html = generate_report_html("Informe", Org, [junk_opp])
    assert "12345 | Agency: Simpler Grants" not in html.replace("&#x27;", "'")
