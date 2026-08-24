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
        assert "500,000" in result["funding_amount_raw"] or "500.000" in result["funding_amount_raw"]

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
