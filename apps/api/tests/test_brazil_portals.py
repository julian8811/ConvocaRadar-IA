"""Tests for the FINEP/Brazilian opportunity portal connector.

F3 (fuentes-cirugia-mayor): ``FinepConnector`` reads the public Liferay
headless custom-object endpoint ``GET /o/c/chamadapublicas`` (no auth) —
the ``/oportunidades`` landing renders its list client-side, so HTML
scraping yields zero. See ``tests/test_finep_api.py`` for real-fixture
coverage; this file pins fetch/validate/routing behaviour.
"""

from __future__ import annotations

import json

import pytest

from app.connectors.base import OpportunityCandidate, RawSourceResult
from app.connectors.brazil_portals import FINEP_API_URL, FinepConnector
from app.connectors.factory import connector_for
from tests.connector_fixtures import apply_fixture_data

_LISTING_URL = "https://www.finep.gov.br/oportunidades"

_SAMPLE_PAYLOAD = {
    "items": [
        {
            "id": 1060720,
            "titulo": "Finep COOPERAMAIS Brasil Tecnologias – Empresas",
            "situacao": {"key": "aberta", "name": "Aberta"},
            "dataDePublicacao": "2026-09-22T00:00:00.000Z",
            "vigenciaInicio": "2026-09-22T00:00:00.000Z",
            "prazoProposto": "2027-04-30T17:00:00.000Z",
            "descricaoRawText": "Seleção pública MCTI/FINEP/FNDCT em fluxo contínuo",
        },
        {
            "id": 968467,
            "titulo": "DESAFIO TECNOLÓGICO ELETROLISADOR NACIONAL",
            "situacao": {"key": "encerrada", "name": "Encerrada"},
            "dataDePublicacao": "2025-01-01T00:00:00.000Z",
            "descricaoRawText": "Desafio encerrado",
        },
    ],
    "totalCount": 478,
}

_EMPTY_PAYLOAD = {"items": [], "totalCount": 478}
_GARBAGE = "not useful content at all"


# ── fetch + parse (using shared connector_factory from conftest) ────────────


class TestFetchAndParse:
    @pytest.mark.asyncio
    async def test_fetch_and_parse_yields_candidates(self, connector_factory):
        connector, mocks = connector_factory(
            "finep-brasil",
            base_url=FINEP_API_URL,
            source_type="html",
        )
        apply_fixture_data(mocks, "httpx-get-html", "sample")
        mocks["fetch_httpx_text"].return_value = (
            FINEP_API_URL,
            json.dumps(_SAMPLE_PAYLOAD),
            "application/json",
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
            base_url=FINEP_API_URL,
            source_type="html",
        )
        apply_fixture_data(mocks, "httpx-get-html", "sample")
        mocks["fetch_httpx_text"].return_value = (
            FINEP_API_URL,
            json.dumps(_SAMPLE_PAYLOAD),
            "application/json",
        )
        raw = await connector.fetch()
        candidates = await connector.parse(raw)
        titles = [c.title for c in candidates]

        assert "Finep COOPERAMAIS Brasil Tecnologias – Empresas" in titles
        # Encerrada history stays out.
        assert "DESAFIO TECNOLÓGICO ELETROLISADOR NACIONAL" not in titles

    @pytest.mark.asyncio
    async def test_parse_empty_items_returns_empty_list(self, connector_factory):
        connector, mocks = connector_factory(
            "finep-brasil",
            base_url=FINEP_API_URL,
            source_type="html",
        )
        apply_fixture_data(mocks, "httpx-get-html", "sample")
        mocks["fetch_httpx_text"].return_value = (
            FINEP_API_URL,
            json.dumps(_EMPTY_PAYLOAD),
            "application/json",
        )
        raw = await connector.fetch()
        candidates = await connector.parse(raw)
        assert candidates == []

    @pytest.mark.asyncio
    async def test_parse_garbage_does_not_raise(self, connector_factory):
        connector, mocks = connector_factory(
            "finep-brasil",
            base_url=FINEP_API_URL,
            source_type="html",
        )
        apply_fixture_data(mocks, "httpx-get-html", "sample")
        mocks["fetch_httpx_text"].return_value = (
            FINEP_API_URL,
            _GARBAGE,
            "application/json",
        )
        raw = await connector.fetch()
        candidates = await connector.parse(raw)
        assert isinstance(candidates, list)

    @pytest.mark.asyncio
    async def test_fetch_raises_on_network_error(self, connector_factory):
        connector, mocks = connector_factory(
            "finep-brasil",
            base_url=FINEP_API_URL,
            source_type="html",
        )
        apply_fixture_data(
            mocks, "httpx-get-html", "sample", side_effect=RuntimeError("simulated network error")
        )

        with pytest.raises(RuntimeError):
            await connector.fetch()


# ── validate tests ──────────────────────────────────────────────────────────


class TestValidate:
    @pytest.mark.asyncio
    async def test_validate_passes_valid_candidate(self, connector_factory):
        connector, _ = connector_factory(
            "finep-brasil",
            base_url=FINEP_API_URL,
            source_type="html",
        )
        candidate = OpportunityCandidate(
            title="Chamada FINEP 2027",
            entity="FINEP",
            country="Brazil",
            official_url=_LISTING_URL,
        )

        result = await connector.validate(candidate)
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_validate_rejects_missing_title(self, connector_factory):
        connector, _ = connector_factory(
            "finep-brasil",
            base_url=FINEP_API_URL,
            source_type="html",
        )
        candidate = OpportunityCandidate(
            title="",
            entity="FINEP",
            country="Brazil",
            official_url=_LISTING_URL,
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
