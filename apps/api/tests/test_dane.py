"""Tests for the DANE Colombia connector.

DANE extends GenericHtmlConnector with parse-time noise filtering:
titles starting with "inicio", "home", "dane -" or containing years
2010–2025 are excluded.
"""

from __future__ import annotations

import pytest

from app.connectors.base import OpportunityCandidate, RawSourceResult
from tests.connector_fixtures import apply_fixture_data

_SAMPLE_HTML = """<html><body>
  <a href="/convocatoria/1">Convocatoria de innovación 2027</a>
  <a href="/convocatoria/2">Convocatoria pública para software</a>
  <a href="/inicio">Inicio</a>
  <a href="/home">Home - DANE</a>
  <a href="/obsoleta">Convocatoria 2020 cerrada</a>
</body></html>"""

_EMPTY_HTML = "<html><body></body></html>"
_GARBAGE_HTML = "not useful content at all"


# ── fetch + parse (using shared connector_factory from conftest) ────────────


class TestFetchAndParse:
    """Integrated fetch+parse via the mocked connector_factory."""

    @pytest.mark.asyncio
    async def test_fetch_and_parse_yields_candidates(self, connector_factory):
        """Happy path: with sample HTML the connector returns >= 1 candidate."""
        connector, mocks = connector_factory(
            "dane-convocatorias",
            base_url="https://www.dane.gov.co/convocatorias",
            source_type="html",
        )
        apply_fixture_data(mocks, "httpx-get-html", "sample")
        # Override sample content with DANE-specific HTML
        mocks["fetch_httpx_text"].return_value = (
            "https://www.dane.gov.co/convocatorias",
            _SAMPLE_HTML,
            "text/html",
        )

        raw = await connector.fetch()
        assert isinstance(raw, RawSourceResult)
        assert raw.source_key == "dane-convocatorias"

        candidates = await connector.parse(raw)
        assert len(candidates) >= 1
        for c in candidates:
            assert isinstance(c, OpportunityCandidate)
            assert c.title

    @pytest.mark.asyncio
    async def test_parse_filters_noise_titles(self, connector_factory):
        """DANE-specific: titles starting with 'inicio', 'home', or
        'dane -', and titles containing years 2010-2025, are removed."""
        connector, mocks = connector_factory(
            "dane-convocatorias",
            base_url="https://www.dane.gov.co/convocatorias",
            source_type="html",
        )
        apply_fixture_data(mocks, "httpx-get-html", "sample")
        mocks["fetch_httpx_text"].return_value = (
            "https://www.dane.gov.co/convocatorias",
            _SAMPLE_HTML,
            "text/html",
        )
        raw = await connector.fetch()
        candidates = await connector.parse(raw)
        titles = [c.title.lower() for c in candidates]

        assert "inicio" not in titles
        assert "home" not in titles
        assert not any("dane -" in t for t in titles)
        assert not any("2020" in t for t in titles)

    @pytest.mark.asyncio
    async def test_parse_keeps_valid_candidates(self, connector_factory):
        """Only the valid convocatorias should survive the DANE noise filter."""
        connector, mocks = connector_factory(
            "dane-convocatorias",
            base_url="https://www.dane.gov.co/convocatorias",
            source_type="html",
        )
        apply_fixture_data(mocks, "httpx-get-html", "sample")
        mocks["fetch_httpx_text"].return_value = (
            "https://www.dane.gov.co/convocatorias",
            _SAMPLE_HTML,
            "text/html",
        )
        raw = await connector.fetch()
        candidates = await connector.parse(raw)
        titles = [c.title for c in candidates]

        assert "Convocatoria de innovación 2027" in titles
        assert "Convocatoria pública para software" in titles

    @pytest.mark.asyncio
    async def test_parse_empty_html_returns_empty_list(self, connector_factory):
        connector, mocks = connector_factory(
            "dane-convocatorias",
            base_url="https://www.dane.gov.co/convocatorias",
            source_type="html",
        )
        apply_fixture_data(mocks, "httpx-get-html", "sample")
        mocks["fetch_httpx_text"].return_value = (
            "https://www.dane.gov.co/convocatorias",
            _EMPTY_HTML,
            "text/html",
        )
        raw = await connector.fetch()
        candidates = await connector.parse(raw)
        assert candidates == []

    @pytest.mark.asyncio
    async def test_parse_garbage_does_not_raise(self, connector_factory):
        connector, mocks = connector_factory(
            "dane-convocatorias",
            base_url="https://www.dane.gov.co/convocatorias",
            source_type="html",
        )
        apply_fixture_data(mocks, "httpx-get-html", "sample")
        mocks["fetch_httpx_text"].return_value = (
            "https://www.dane.gov.co/convocatorias",
            _GARBAGE_HTML,
            "text/html",
        )
        raw = await connector.fetch()
        candidates = await connector.parse(raw)
        assert isinstance(candidates, list)

    @pytest.mark.asyncio
    async def test_fetch_raises_on_network_error(self, connector_factory):
        connector, mocks = connector_factory(
            "dane-convocatorias",
            base_url="https://www.dane.gov.co/convocatorias",
            source_type="html",
        )
        apply_fixture_data(
            mocks, "httpx-get-html", "sample", side_effect=RuntimeError("simulated network error")
        )

        with pytest.raises(RuntimeError):
            await connector.fetch()


# ── validate tests ─────────────────────────────────────────────────────────


class TestValidate:
    @pytest.mark.asyncio
    async def test_validate_passes_valid_candidate(self, connector_factory):
        connector, _ = connector_factory(
            "dane-convocatorias",
            base_url="https://www.dane.gov.co/convocatorias",
            source_type="html",
        )
        candidate = OpportunityCandidate(
            title="Convocatoria DANE 2027",
            entity="DANE",
            country="Colombia",
            official_url="https://www.dane.gov.co/convocatorias/1",
        )

        result = await connector.validate(candidate)
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_validate_rejects_missing_title(self, connector_factory):
        connector, _ = connector_factory(
            "dane-convocatorias",
            base_url="https://www.dane.gov.co/convocatorias",
            source_type="html",
        )
        candidate = OpportunityCandidate(
            title="",
            entity="DANE",
            country="Colombia",
            official_url="https://www.dane.gov.co/convocatorias/1",
        )

        result = await connector.validate(candidate)
        assert result.ok is False

    @pytest.mark.asyncio
    async def test_validate_rejects_missing_url(self, connector_factory):
        connector, _ = connector_factory(
            "dane-convocatorias",
            base_url="https://www.dane.gov.co/convocatorias",
            source_type="html",
        )
        candidate = OpportunityCandidate(
            title="Convocatoria DANE",
            entity="DANE",
            country="Colombia",
            official_url="",
        )

        result = await connector.validate(candidate)
        assert result.ok is False
