"""F3 (fuentes-cirugia-mayor): FINEP via Liferay headless custom-object API.

TDD RED->GREEN: ``FinepConnector`` es ``GenericHtmlConnector`` sin overrides;
la landing Liferay (``/oportunidades``) no trae chamadas en SSR (lista CSR
via bundle ``/o/finep-busca-chamadas-publicas/``). Fixture JSON real (podado)
de ``GET https://www.finep.gov.br/o/c/chamadapublicas?sort=dataDePublicacao:desc``
(2026-10-10, totalCount=478, pageSize=500 en 1 sola pagina; 6 items: 4
abertas + 1 sin situacao (EUREKA vigente) + 1 encerrada que debe filtrarse).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from app.connectors.base import RawSourceResult
from app.connectors.brazil_portals import FinepConnector
from app.connectors.factory import connector_for
from tests.connector_fixtures import apply_fixture_data

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "finep_chamadas_publicas.json"
)
FINEP_API_URL = (
    "https://www.finep.gov.br/o/c/chamadapublicas?sort=dataDePublicacao:desc"
)
FINEP_LISTING_URL = "https://www.finep.gov.br/oportunidades"


def _seed_definitions_by_key() -> dict[str, dict]:
    seed_path = Path(__file__).resolve().parents[1] / "app" / "db" / "seed.py"
    tree = ast.parse(seed_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name != "seed_default_sources":
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == "source_definitions":
                    return {item["key"]: item for item in ast.literal_eval(stmt.value)}
    raise AssertionError("source_definitions not found")


class TestFinepApiParse:
    @pytest.mark.asyncio
    async def test_parse_real_fixture_yields_five(self, connector_factory):
        connector, mocks = connector_factory(
            "finep-brasil", base_url=FINEP_API_URL, source_type="html"
        )
        apply_fixture_data(mocks, "httpx-get-html", "sample")
        mocks["fetch_httpx_text"].return_value = (
            FINEP_API_URL,
            FIXTURE_PATH.read_text(encoding="utf-8"),
            "application/json",
        )
        raw = await connector.fetch()
        candidates = await connector.parse(raw)
        # 4 abertas + EUREKA (sin situacao, vigente); la encerrada se filtra.
        assert len(candidates) == 5
        titles = [c.title for c in candidates]
        assert any("COOPERAMAIS" in t for t in titles)
        assert any("EUREKA" in t for t in titles)
        assert not any("ELETROLISADOR" in t for t in titles)

    @pytest.mark.asyncio
    async def test_official_url_is_listing_page(self, connector_factory):
        connector, mocks = connector_factory(
            "finep-brasil", base_url=FINEP_API_URL, source_type="html"
        )
        apply_fixture_data(mocks, "httpx-get-html", "sample")
        mocks["fetch_httpx_text"].return_value = (
            FINEP_API_URL,
            FIXTURE_PATH.read_text(encoding="utf-8"),
            "application/json",
        )
        candidates = await connector.parse(await connector.fetch())
        for c in candidates:
            assert c.official_url == FINEP_LISTING_URL

    @pytest.mark.asyncio
    async def test_close_date_from_prazo_proposto(self, connector_factory):
        connector, mocks = connector_factory(
            "finep-brasil", base_url=FINEP_API_URL, source_type="html"
        )
        apply_fixture_data(mocks, "httpx-get-html", "sample")
        mocks["fetch_httpx_text"].return_value = (
            FINEP_API_URL,
            FIXTURE_PATH.read_text(encoding="utf-8"),
            "application/json",
        )
        candidates = await connector.parse(await connector.fetch())
        by_id = {c.external_id: c for c in candidates}
        # COOPERAMAIS Empresas: prazoProposto 2027-04-30T17:00:00.
        assert by_id["1060720"].close_date is not None
        assert (by_id["1060720"].close_date.year, by_id["1060720"].close_date.month) == (
            2027,
            4,
        )
        # EUREKA sin situacao: plazo propuesto 2026-11-06 (manda sobre vigenciaFim).
        assert by_id["1075469"].close_date is not None
        assert (by_id["1075469"].close_date.year, by_id["1075469"].close_date.month) == (
            2026,
            11,
        )

    @pytest.mark.asyncio
    async def test_parse_garbage_returns_empty(self, connector_factory):
        connector, mocks = connector_factory(
            "finep-brasil", base_url=FINEP_API_URL, source_type="html"
        )
        apply_fixture_data(mocks, "httpx-get-html", "sample")
        mocks["fetch_httpx_text"].return_value = (
            FINEP_API_URL,
            "not useful content at all",
            "application/json",
        )
        raw = await connector.fetch()
        assert await connector.parse(raw) == []


class TestFinepApiValidate:
    @pytest.mark.asyncio
    async def test_validate_rejects_missing_title(self, connector_factory):
        connector, _ = connector_factory(
            "finep-brasil", base_url=FINEP_API_URL, source_type="html"
        )
        candidates = await connector.parse(
            RawSourceResult(
                source_key="finep-brasil",
                url=FINEP_API_URL,
                content=json.dumps({"items": [{"id": 1, "titulo": ""}]}),
                content_type="application/json",
            )
        )
        assert candidates == []

    def test_routing_returns_finep_connector(self):
        conn = connector_for("finep-brasil", "http://example.com", "html")
        assert isinstance(conn, FinepConnector)
        assert conn.source_key == "finep-brasil"


class TestFinepApiSeed:
    def test_seed_base_url_points_to_chamadas_api(self):
        definition = _seed_definitions_by_key()["finep-brasil"]
        assert "/o/c/chamadapublicas" in definition["base_url"]
        assert "finep.gov.br" in definition["base_url"]
