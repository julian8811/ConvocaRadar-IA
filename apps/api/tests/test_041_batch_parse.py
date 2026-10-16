"""041 parse fixtures for 5-source agro/biodiversity expansion. Mocked fetch only.

Diseno anti-ruido por fuente: selectores anclados a rutas de convocatorias
(convocatoria/call) para no importar noticias, empleos ni licitaciones.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.connectors.configurable_html import ConfigurableHtmlConnector

BATCH = {
    "fontagro-convocatorias": {
        "url": "https://fontagro.org/es/iniciativas/convocatorias",
        "entity": "FONTAGRO",
        "html": """<html><body><main>
<article><h2><a href="/es/iniciativas/convocatorias/convocatoria-2027">Convocatoria 2027 FONTAGRO I+D+i agroalimentaria</a></h2></article>
<article><h2><a href="/es/iniciativas/convocatorias/convocatoria-2026">Convocatoria 2026 consorcios regionales de innovacion</a></h2></article>
</main></body></html>""",
        "titles": ("Convocatoria 2027", "Convocatoria 2026"),
    },
    "fundacion-biodiversidad-convocatorias": {
        "url": "https://fundacion-biodiversidad.es/buscador-de-convocatorias/",
        "entity": "Fundacion Biodiversidad",
        "html": """<html><body><main>
<article><h2><a href="/otras_convocatorias/convocatoria-para-proyectos-de-educacion-ambiental-2">Convocatoria para proyectos de Educacion Ambiental 2026</a></h2></article>
<article><h2><a href="/otras_convocatorias/convocatoria-infraestructura-verde-ciudades-2026">Convocatoria renaturalizacion y resiliencia de ciudades 2026</a></h2></article>
</main></body></html>""",
        "titles": ("Educacion Ambiental", "renaturalizacion"),
    },
    "eu-life-calls-cinea": {
        "url": "https://cinea.ec.europa.eu/life-calls-proposals-2026_en",
        "entity": "CINEA EU LIFE",
        "html": """<html><body><main>
<article><h2><a href="/life-calls-proposals-2026/sap-circular-economy">LIFE 2026 Standard Action Projects Circular Economy call</a></h2></article>
<article><h2><a href="/life-calls-proposals-2026/sap-nature-biodiversity">LIFE 2026 Nature and Biodiversity call for proposals</a></h2></article>
</main></body></html>""",
        "titles": ("Circular Economy", "Nature and Biodiversity"),
    },
    "biodiversa-calls": {
        "url": "https://www.biodiversa.eu/research-funding/upcoming-calls",
        "entity": "Biodiversa+",
        "html": """<html><body><main>
<article><h2><a href="/2026/06/09/2026-2027-joint-call">BiodivFuture 2026-2027 Joint Call for transnational research</a></h2></article>
</main></body></html>""",
        "titles": ("BiodivFuture",),
    },
    "fondo-accion-convocatorias": {
        "url": "https://fondoaccion.org/convocatorias/",
        "entity": "Fondo Accion",
        "html": """<html><body><main>
<article><h2><a href="/2026/08/12/lab-csielo-convocatoria/">Becas Laboratorio Acciones Escolares Climaticas CSIELO</a></h2></article>
<article><h2><a href="/convocatorias/territorios-mas-sostenibles">Convocatoria Territorios Mas Sostenibles adaptacion climatica</a></h2></article>
</main></body></html>""",
        "titles": ("CSIELO", "Territorios Mas Sostenibles"),
    },
}


def _seed_config(key: str) -> dict:
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
                    defs = {item["key"]: item for item in ast.literal_eval(stmt.value)}
                    return defs[key]["connector_config"]
    raise AssertionError(f"config missing for {key}")


@pytest.mark.asyncio
@pytest.mark.parametrize("key", list(BATCH))
async def test_041_parse_fixture(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    meta = BATCH[key]
    mock = AsyncMock(return_value=(meta["url"], meta["html"], "text/html"))
    monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)
    connector = ConfigurableHtmlConnector(
        key,
        meta["url"],
        _seed_config(key),
        entity_name=meta["entity"],
        default_country="International",
    )
    raw = await connector.fetch()
    candidates = await connector.parse(raw)
    assert len(candidates) >= 1, f"{key} yielded 0 candidates"
    titles = {c.title for c in candidates}
    assert any(
        any(expected.lower() in title.lower() for title in titles)
        for expected in meta["titles"]
    ), titles


@pytest.mark.asyncio
async def test_041_probe_batch_total_titles(monkeypatch: pytest.MonkeyPatch) -> None:
    total = 0
    for key, meta in BATCH.items():
        mock = AsyncMock(return_value=(meta["url"], meta["html"], "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)
        connector = ConfigurableHtmlConnector(key, meta["url"], _seed_config(key), entity_name=meta["entity"], default_country="International")
        raw = await connector.fetch()
        candidates = await connector.parse(raw)
        assert len(candidates) >= 1, f"{key} smoke 0"
        total += len(candidates)
    assert total >= 5, f"probe total {total} < 5"


@pytest.mark.asyncio
async def test_041_smoke_per_seed_ge_one(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, meta in BATCH.items():
        mock = AsyncMock(return_value=(meta["url"], meta["html"], "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)
        connector = ConfigurableHtmlConnector(key, meta["url"], _seed_config(key), entity_name=meta["entity"], default_country="International")
        raw = await connector.fetch()
        candidates = await connector.parse(raw)
        assert len(candidates) >= 1
        c = candidates[0]
        assert c.title and len(c.title) >= 4
        assert c.official_url.startswith("http")
