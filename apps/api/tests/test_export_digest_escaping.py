"""Escaping-correctness tests for delivered HTML surfaces.

``generate_report_html`` (export.py) and ``build_weekly_digest_html``
(genai.py) render scraped content into HTML emails/reports. They must route
text through ``app.core.text.safe_escape`` so pre-encoded entities from
source pages are displayed decoded exactly once, active markup stays escaped,
and URL query strings keep a single ``&amp;`` per ampersand.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.export import generate_report_html
from app.services.genai import build_weekly_digest_html


def _opportunity(**overrides):
    base = dict(
        source_id="src-1",
        status="open",
        country="Colombia",
        title="Beca <b>destacada</b>",
        entity="Fundaci&oacute;n Carvajal",
        summary="Apoya proyectos &aacute;ridos de investigación",
        description=None,
        close_date=None,
        funding_amount_raw="",
        funding_amount_value=None,
        categories=["Ciencia"],
        official_url="https://example.org/call?id=7&lang=es",
        application_url=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestReportHtmlEscaping:
    def test_entity_is_decoded_once_in_report_body(self) -> None:
        html = generate_report_html("Reporte", SimpleNamespace(name="Uni"), [_opportunity()])
        assert "Fundación Carvajal" in html
        assert "&amp;oacute;" not in html

    def test_summary_entity_is_decoded_once(self) -> None:
        html = generate_report_html("Reporte", SimpleNamespace(name="Uni"), [_opportunity()])
        assert "áridos" in html
        assert "&amp;aacute;" not in html

    def test_title_markup_stays_escaped_in_card(self) -> None:
        html = generate_report_html("Reporte", SimpleNamespace(name="Uni"), [_opportunity()])
        assert "&lt;b&gt;destacada&lt;/b&gt;" in html
        assert "<b>destacada" not in html

    def test_report_title_is_decoded_once_in_title_tag(self) -> None:
        html = generate_report_html("Reporte &uacute;nico", SimpleNamespace(name="Uni"), [_opportunity()])
        assert "<title>Reporte único</title>" in html
        assert "&amp;uacute;" not in html

    def test_url_query_ampersand_is_escaped_exactly_once(self) -> None:
        html = generate_report_html("Reporte", SimpleNamespace(name="Uni"), [_opportunity()])
        assert 'href="https://example.org/call?id=7&amp;lang=es"' in html
        assert "&amp;amp;" not in html


class TestWeeklyDigestEscaping:
    def test_digest_renders_entities_decoded_once(self) -> None:
        org = SimpleNamespace(name="Gesti&oacute;n &Uacute;nica")
        opp = _opportunity(title="Convocatoria &ntilde;and&uacute; &aacute;gil")
        html = build_weekly_digest_html(organization=org, opportunities=[opp])
        assert "Gestión Única" in html
        assert "Convocatoria ñandú ágil" in html
        assert "&amp;ntilde;" not in html
        assert "&amp;Uacute;" not in html

    def test_digest_url_ampersand_is_escaped_exactly_once(self) -> None:
        org = SimpleNamespace(name="Org")
        html = build_weekly_digest_html(organization=org, opportunities=[_opportunity()])
        assert "href='https://example.org/call?id=7&amp;lang=es'" in html
        assert "&amp;amp;" not in html
