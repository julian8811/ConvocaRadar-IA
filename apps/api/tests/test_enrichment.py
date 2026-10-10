"""Tests for detail-page enrichment of sitemap-based candidates.

Sitemap connectors (findeter, uniandes, developmentaid) create low-confidence
candidates from URL slugs. This suite verifies that detail-page enrichment
extracts close dates and funding amounts from the actual opportunity pages.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.connectors.common import enrich_from_detail_page


# ── E1 pilot detail enrichment (runner-level, 3 pilot sources) ─────────────

_PILOT_DETAIL_HTML = """<html><body>
  <h1 class="name">Convocatoria de Ciencia 2026</h1>
  <div class="content">
    <p>Apertura: 1 de agosto de 2026</p>
    <p>Fecha de cierre: 30 de septiembre de 2026</p>
    <p>Presupuesto: USD 500,000</p>
    <p>El proyecto busca fortalecer capacidades institucionales de investigacion...</p>
  </div>
</body></html>"""


def _pilot_candidate(url: str = "https://minciencias.gov.co/convocatorias/ciencia-2026"):
    from app.connectors.base import OpportunityCandidate

    return OpportunityCandidate(
        title="Convocatoria de ciencia",
        entity="Minciencias",
        country="Colombia",
        official_url=url,
        summary="Convocatoria de ciencia",
        raw_text="Convocatoria de ciencia",
        confidence_score=0.72,
    )


def _mock_detail_page(monkeypatch, html: str = _PILOT_DETAIL_HTML):
    from unittest.mock import AsyncMock

    mock_fetch = AsyncMock()
    mock_fetch.return_value = ("https://detail.example/item", html, "text/html")
    monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock_fetch)
    return mock_fetch


class TestPilotDetailEnrichment:
    @pytest.mark.asyncio
    async def test_pilot_candidate_gains_close_date_and_funding(self, monkeypatch):
        from app.connectors.common import enrich_pilot_candidates

        _mock_detail_page(monkeypatch)

        result = await enrich_pilot_candidates("minciencias", [_pilot_candidate()])

        assert len(result) == 1
        enriched = result[0]
        assert enriched.close_date is not None
        assert (enriched.close_date.year, enriched.close_date.month, enriched.close_date.day) == (
            2026,
            9,
            30,
        )
        assert enriched.funding_amount_raw is not None
        assert "500,000" in enriched.funding_amount_raw or "500.000" in enriched.funding_amount_raw

    @pytest.mark.asyncio
    async def test_non_pilot_source_skips_detail_fetch(self, monkeypatch):
        from app.connectors.common import enrich_pilot_candidates

        mock_fetch = _mock_detail_page(monkeypatch)
        candidate = _pilot_candidate(url="https://novonordiskfonden.dk/grant-1")

        result = await enrich_pilot_candidates("novo-nordisk-grants", [candidate])

        assert result == [candidate]
        mock_fetch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_complete_candidates_skip_detail_fetch(self, monkeypatch):
        from datetime import datetime as _dt

        from app.connectors.common import enrich_pilot_candidates

        mock_fetch = _mock_detail_page(monkeypatch)
        candidate = _pilot_candidate()
        candidate.close_date = _dt(2026, 10, 31)
        candidate.open_date = _dt(2026, 8, 1)
        candidate.funding_amount_raw = "USD 10,000"

        result = await enrich_pilot_candidates("innpulsa", [candidate])

        assert result[0].close_date == _dt(2026, 10, 31)
        mock_fetch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_existing_close_date_never_overwritten(self, monkeypatch):
        from datetime import datetime as _dt

        from app.connectors.common import enrich_pilot_candidates

        _mock_detail_page(monkeypatch)
        candidate = _pilot_candidate()
        candidate.close_date = _dt(2026, 10, 31)

        result = await enrich_pilot_candidates("grants-gov", [candidate])

        # Detail page says 2026-09-30; list value must win.
        assert result[0].close_date == _dt(2026, 10, 31)

    @pytest.mark.asyncio
    async def test_runner_enriches_pilot_source(self, monkeypatch):
        from unittest.mock import AsyncMock

        from app.connectors.base import RawSourceResult, ValidationResult
        from app.models import Source
        from app.scraper.runner import _scrape_candidates

        _mock_detail_page(monkeypatch)

        class _FakeConnector:
            async def fetch(self):
                return RawSourceResult(
                    source_key="minciencias",
                    url="https://minciencias.gov.co/convocatorias/todas",
                    content="<html></html>",
                    content_type="text/html",
                )

            async def parse(self, raw):
                return [_pilot_candidate()]

            async def validate(self, candidate):
                return ValidationResult(ok=True)

        monkeypatch.setattr(
            "app.connectors.factory.connector_for", lambda *a, **k: _FakeConnector()
        )
        source = Source(
            name="Minciencias",
            key="minciencias",
            base_url="https://minciencias.gov.co/convocatorias/todas",
        )

        opportunities = await _scrape_candidates(source)

        assert len(opportunities) == 1
        assert opportunities[0].close_date is not None
        assert (opportunities[0].close_date.year, opportunities[0].close_date.month) == (2026, 9)

    @pytest.mark.asyncio
    async def test_runner_skips_enrichment_for_non_pilot(self, monkeypatch):
        from app.connectors.base import RawSourceResult, ValidationResult
        from app.models import Source
        from app.scraper.runner import _scrape_candidates

        mock_fetch = _mock_detail_page(monkeypatch)

        class _FakeConnector:
            async def fetch(self):
                return RawSourceResult(
                    source_key="novo-nordisk-grants",
                    url="https://example.com/api",
                    content="<html></html>",
                    content_type="text/html",
                )

            async def parse(self, raw):
                return [_pilot_candidate(url="https://novonordiskfonden.dk/grant-1")]

            async def validate(self, candidate):
                return ValidationResult(ok=True)

        monkeypatch.setattr(
            "app.connectors.factory.connector_for", lambda *a, **k: _FakeConnector()
        )
        source = Source(
            name="Novo Nordisk",
            key="novo-nordisk-grants",
            base_url="https://example.com/api",
        )

        opportunities = await _scrape_candidates(source)

        assert len(opportunities) == 1
        assert opportunities[0].close_date is None
        mock_fetch.assert_not_awaited()


# ── Sample HTML with close date and funding amount ────────────────────────

_SAMPLE_DETAIL_HTML = """<html><body>
  <h1 class="name">Convocatoria para Consultoría</h1>
  <div class="content">
    <p>Financiamiento: USD 500,000</p>
    <p>Fecha de cierre: 30 de septiembre de 2026</p>
    <p>Presupuesto: USD 500,000</p>
    <p>El proyecto busca fortalecer capacidades institucionales...</p>
  </div>
  <meta property="og:title" content="Convocatoria para Consultoría" />
  <meta property="og:description" content="Financiamiento: USD 500,000" />
</body></html>"""

_SAMPLE_DETAIL_NO_DATES = """<html><body>
  <h1>Convocatoria cerrada</h1>
  <p>Esta convocatoria ya no está disponible.</p>
</body></html>"""

_SAMPLE_GARBAGE = "not html at all"


# ── Tests ─────────────────────────────────────────────────────────────────


class TestEnrichFromDetailPage:
    @pytest.mark.asyncio
    async def test_enrich_extracts_close_date(self, monkeypatch):
        mock_fetch = AsyncMock()
        mock_fetch.return_value = (
            "https://example.com/detail/1",
            _SAMPLE_DETAIL_HTML,
            "text/html",
        )
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock_fetch)

        # Disable deep-fetch timeout limit
        result = await enrich_from_detail_page("https://example.com/detail/1")

        assert result is not None
        assert result.get("close_date") is not None
        cd = result["close_date"]
        if isinstance(cd, datetime):
            assert cd.year == 2026
            assert cd.month == 9
            assert cd.day == 30

    @pytest.mark.asyncio
    async def test_enrich_extracts_funding_amount(self, monkeypatch):
        mock_fetch = AsyncMock()
        mock_fetch.return_value = (
            "https://example.com/detail/1",
            _SAMPLE_DETAIL_HTML,
            "text/html",
        )
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock_fetch)

        result = await enrich_from_detail_page("https://example.com/detail/1")

        assert result is not None
        assert result.get("funding_amount_raw") is not None
        assert (
            "500,000" in result["funding_amount_raw"] or "500.000" in result["funding_amount_raw"]
        )

    @pytest.mark.asyncio
    async def test_enrich_extracts_title_from_h1(self, monkeypatch):
        mock_fetch = AsyncMock()
        mock_fetch.return_value = (
            "https://example.com/detail/1",
            _SAMPLE_DETAIL_HTML,
            "text/html",
        )
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock_fetch)

        result = await enrich_from_detail_page("https://example.com/detail/1")

        assert result is not None
        assert result.get("title") == "Convocatoria para Consultoría"

    @pytest.mark.asyncio
    async def test_enrich_returns_none_on_fetch_failure(self, monkeypatch):
        mock_fetch = AsyncMock()
        mock_fetch.side_effect = RuntimeError("Connection failed")
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock_fetch)

        result = await enrich_from_detail_page("https://example.com/detail/1")
        assert result is None

    @pytest.mark.asyncio
    async def test_enrich_handles_garbage_html(self, monkeypatch):
        mock_fetch = AsyncMock()
        mock_fetch.return_value = (
            "https://example.com/detail/1",
            _SAMPLE_GARBAGE,
            "text/html",
        )
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock_fetch)

        result = await enrich_from_detail_page("https://example.com/detail/1")
        assert result is None or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_enrich_handles_page_with_no_dates(self, monkeypatch):
        mock_fetch = AsyncMock()
        mock_fetch.return_value = (
            "https://example.com/detail/1",
            _SAMPLE_DETAIL_NO_DATES,
            "text/html",
        )
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock_fetch)

        result = await enrich_from_detail_page("https://example.com/detail/1")
        # Should still return something if there's a title
        assert result is not None
        assert "title" in result
