"""Tanda A (fuentes-todas-on): FAPEMIG wp-json fix + pines de dictamen.

TDD RED->GREEN: ``FapemigConnector`` no existe hasta el fix; el import falla
en RED. Fixture JSON real (podado) de
``GET .../wp-json/fapemig-chamadas-e-editais/v1/chamadas?status=aberta``
(2026-10-10, 4 items, total=4 page=1).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from app.connectors.base import RawSourceResult
from app.connectors.brazil_portals import FapemigConnector
from app.connectors.factory import connector_for
from tests.connector_fixtures import apply_fixture_data

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "fapemig_chamadas_abertas.json"
)
FAPEMIG_API_URL = (
    "https://api.site.fapemig.br/wp-json/fapemig-chamadas-e-editais/v1/chamadas"
    "?status=aberta"
)

# HTML realista estilo Findeter: snippet analytics PerfDrive (sano) + links.
# Pina el fix T2 de `_is_challenge_page` (el bare "perfdrive" NO es challenge).
_FINDETER_HTML = """<html><head><title>FINDETER : Convocatorias</title>
<script>ssConf("cu", "validate.perfdrive.com, ssc");</script></head><body>
<a href="/convocatorias/paf-atmindeporte-o-052-2026">PAF-ATMINDEPORTE-O-052-2026</a>
<a href="/convocatorias/paf-fonpaz-o-049-2025">PAF-FONPAZ-O-049-2025</a>
</body></html>"""


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


class TestFapemigParse:
    @pytest.mark.asyncio
    async def test_parse_real_fixture_yields_four(self, connector_factory):
        connector, mocks = connector_factory(
            "fapemig-brasil", base_url=FAPEMIG_API_URL, source_type="html"
        )
        apply_fixture_data(mocks, "httpx-get-html", "sample")
        mocks["fetch_httpx_text"].return_value = (
            FAPEMIG_API_URL,
            FIXTURE_PATH.read_text(encoding="utf-8"),
            "application/json",
        )
        raw = await connector.fetch()
        candidates = await connector.parse(raw)
        assert len(candidates) == 4
        titles = [c.title for c in candidates]
        assert any("HUBMG" in t for t in titles)
        assert any("PROFIX" in t or "17/2026" in t for t in titles)

    @pytest.mark.asyncio
    async def test_official_url_built_from_slug(self, connector_factory):
        connector, mocks = connector_factory(
            "fapemig-brasil", base_url=FAPEMIG_API_URL, source_type="html"
        )
        apply_fixture_data(mocks, "httpx-get-html", "sample")
        mocks["fetch_httpx_text"].return_value = (
            FAPEMIG_API_URL,
            FIXTURE_PATH.read_text(encoding="utf-8"),
            "application/json",
        )
        candidates = await connector.parse(await connector.fetch())
        for c in candidates:
            assert c.official_url.startswith(
                "https://fapemig.br/oportunidades/chamadas-e-editais/"
            )

    @pytest.mark.asyncio
    async def test_close_date_from_data_fim_submissao(self, connector_factory):
        connector, mocks = connector_factory(
            "fapemig-brasil", base_url=FAPEMIG_API_URL, source_type="html"
        )
        apply_fixture_data(mocks, "httpx-get-html", "sample")
        mocks["fetch_httpx_text"].return_value = (
            FAPEMIG_API_URL,
            FIXTURE_PATH.read_text(encoding="utf-8"),
            "application/json",
        )
        candidates = await connector.parse(await connector.fetch())
        by_id = {c.external_id: c for c in candidates}
        assert by_id["195"].close_date is not None
        assert (by_id["195"].close_date.year, by_id["195"].close_date.month) == (
            2026,
            12,
        )

    @pytest.mark.asyncio
    async def test_parse_empty_returns_empty(self, connector_factory):
        connector, mocks = connector_factory(
            "fapemig-brasil", base_url=FAPEMIG_API_URL, source_type="html"
        )
        apply_fixture_data(mocks, "httpx-get-html", "sample")
        mocks["fetch_httpx_text"].return_value = (
            FAPEMIG_API_URL,
            '{"data": [], "total": 0}',
            "application/json",
        )
        candidates = await connector.parse(await connector.fetch())
        assert candidates == []

    @pytest.mark.asyncio
    async def test_parse_garbage_does_not_raise(self, connector_factory):
        connector, _ = connector_factory(
            "fapemig-brasil", base_url=FAPEMIG_API_URL, source_type="html"
        )
        raw = RawSourceResult(
            source_key="fapemig-brasil",
            url=FAPEMIG_API_URL,
            content="not useful content at all",
            content_type="application/json",
        )
        assert await connector.parse(raw) == []


class TestFapemigValidate:
    @pytest.mark.asyncio
    async def test_validate_rejects_missing_title(self, connector_factory):
        connector, _ = connector_factory(
            "fapemig-brasil", base_url=FAPEMIG_API_URL, source_type="html"
        )
        candidates = await connector.parse(
            RawSourceResult(
                source_key="fapemig-brasil",
                url=FAPEMIG_API_URL,
                content=json.dumps({"data": [{"id": 1, "slug": "x", "titulo": ""}]}),
                content_type="application/json",
            )
        )
        assert candidates == []

    def test_routing_returns_fapemig_connector(self):
        conn = connector_for("fapemig-brasil", "http://example.com", "html")
        assert isinstance(conn, FapemigConnector)
        assert conn.source_key == "fapemig-brasil"


class TestFapemigSeed:
    def test_seed_base_url_points_to_chamadas_api(self):
        definition = _seed_definitions_by_key()["fapemig-brasil"]
        assert "wp-json/fapemig-chamadas-e-editais/v1/chamadas" in definition["base_url"]
        assert "api.site.fapemig.br" in definition["allowed_domains"]


class TestFindeterDictamenPin:
    """La DOM local sigue sana: el snippet PerfDrive NO es challenge y el
    fallback HTML extrae los links de detalle (evidencia dictamen tanda A)."""

    def test_perfdrive_analytics_snippet_is_not_challenge(self):
        from app.connectors.findeter import _is_challenge_page

        assert _is_challenge_page(_FINDETER_HTML) is False

    @pytest.mark.asyncio
    async def test_html_fallback_extracts_detail_links(self):
        from app.connectors.findeter import FindeterConnector

        connector = FindeterConnector("https://www.findeter.gov.co/convocatorias")
        raw = RawSourceResult(
            source_key="findeter-convocatorias",
            url="https://www.findeter.gov.co/convocatorias",
            content=_FINDETER_HTML,
            content_type="text/html",
        )
        candidates = await connector.parse(raw)
        assert len(candidates) == 2
        assert all("/convocatorias/" in c.official_url for c in candidates)
