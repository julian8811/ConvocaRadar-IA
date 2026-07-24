"""Tests for the FINEP/Brazilian opportunity portal connector.

FinepConnector extends GenericHtmlConnector without overrides — it exists
as a dedicated type so the factory can route ``finep-brasil`` to a
specific class for future customisation.
"""

from __future__ import annotations

import pytest

from app.connectors.base import OpportunityCandidate, RawSourceResult
from app.connectors.brazil_portals import FinepConnector
from app.connectors.factory import connector_for
from tests.connector_fixtures import apply_fixture_data

_SAMPLE_HTML = """<html><body>
  <a href="/chamada/1">Chamada Pública para Inovação 2027</a>
  <a href="/chamada/2">Chamada Econômica para Startups</a>
</body></html>"""

_EMPTY_HTML = "<html><body></body></html>"
_GARBAGE_HTML = "not useful content at all"


# ── fetch + parse (using shared connector_factory from conftest) ────────────


class TestFetchAndParse:
    @pytest.mark.asyncio
    async def test_fetch_and_parse_yields_candidates(self, connector_factory):
        connector, mocks = connector_factory(
            "finep-brasil",
            base_url="https://www.finep.gov.br/oportunidades",
            source_type="html",
        )
        apply_fixture_data(mocks, "httpx-get-html", "sample")
        mocks["fetch_httpx_text"].return_value = (
            "https://www.finep.gov.br/oportunidades",
            _SAMPLE_HTML,
            "text/html",
        )

        raw = await connector.fetch()
        assert isinstance(raw, RawSourceResult)
        assert raw.source_key == "finep-brasil"

        candidates = await connector.parse(raw)
        assert len(candidates) >= 1
        for c in candidates:
            assert isinstance(c, OpportunityCandidate)
            assert c.title

    @pytest.mark.asyncio
    async def test_parse_extracts_chamadas_publicas(self, connector_factory):
        connector, mocks = connector_factory(
            "finep-brasil",
            base_url="https://www.finep.gov.br/oportunidades",
            source_type="html",
        )
        apply_fixture_data(mocks, "httpx-get-html", "sample")
        mocks["fetch_httpx_text"].return_value = (
            "https://www.finep.gov.br/oportunidades",
            _SAMPLE_HTML,
            "text/html",
        )
        raw = await connector.fetch()
        candidates = await connector.parse(raw)
        titles = [c.title for c in candidates]

        assert "Chamada Pública para Inovação 2027" in titles
        assert "Chamada Econômica para Startups" in titles

    @pytest.mark.asyncio
    async def test_parse_empty_html_returns_empty_list(self, connector_factory):
        connector, mocks = connector_factory(
            "finep-brasil",
            base_url="https://www.finep.gov.br/oportunidades",
            source_type="html",
        )
        apply_fixture_data(mocks, "httpx-get-html", "sample")
        mocks["fetch_httpx_text"].return_value = (
            "https://www.finep.gov.br/oportunidades",
            _EMPTY_HTML,
            "text/html",
        )
        raw = await connector.fetch()
        candidates = await connector.parse(raw)
        assert candidates == []

    @pytest.mark.asyncio
    async def test_parse_garbage_does_not_raise(self, connector_factory):
        connector, mocks = connector_factory(
            "finep-brasil",
            base_url="https://www.finep.gov.br/oportunidades",
            source_type="html",
        )
        apply_fixture_data(mocks, "httpx-get-html", "sample")
        mocks["fetch_httpx_text"].return_value = (
            "https://www.finep.gov.br/oportunidades",
            _GARBAGE_HTML,
            "text/html",
        )
        raw = await connector.fetch()
        candidates = await connector.parse(raw)
        assert isinstance(candidates, list)

    @pytest.mark.asyncio
    async def test_fetch_raises_on_network_error(self, connector_factory):
        connector, mocks = connector_factory(
            "finep-brasil",
            base_url="https://www.finep.gov.br/oportunidades",
            source_type="html",
        )
        apply_fixture_data(mocks, "httpx-get-html", "sample", side_effect=RuntimeError("simulated network error"))

        with pytest.raises(RuntimeError):
            await connector.fetch()


# ── validate tests ──────────────────────────────────────────────────────────


class TestValidate:
    @pytest.mark.asyncio
    async def test_validate_passes_valid_candidate(self, connector_factory):
        connector, _ = connector_factory(
            "finep-brasil",
            base_url="https://www.finep.gov.br/oportunidades",
            source_type="html",
        )
        candidate = OpportunityCandidate(
            title="Chamada FINEP 2027",
            entity="FINEP",
            country="Brazil",
            official_url="https://www.finep.gov.br/chamada/1",
        )

        result = await connector.validate(candidate)
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_validate_rejects_missing_title(self, connector_factory):
        connector, _ = connector_factory(
            "finep-brasil",
            base_url="https://www.finep.gov.br/oportunidades",
            source_type="html",
        )
        candidate = OpportunityCandidate(
            title="",
            entity="FINEP",
            country="Brazil",
            official_url="https://www.finep.gov.br/chamada/1",
        )

        result = await connector.validate(candidate)
        assert result.ok is False


# ── type / routing tests ────────────────────────────────────────────────────


class TestConnectorType:
    def test_is_finep_connector(self):
        conn = connector_for(
            "finep-brasil",
            "http://example.com",
            entity_name="FINEP",
            default_country="Brazil",
        )
        assert isinstance(conn, FinepConnector)

    def test_connector_for_returns_finep_instance(self):
        conn = connector_for(
            "finep-brasil",
            "http://example.com",
            entity_name="FINEP",
            default_country="Brazil",
        )
        assert conn.source_key == "finep-brasil"
