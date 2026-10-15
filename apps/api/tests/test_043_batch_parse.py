"""043 parse fixtures for tourism expansion. Mocked fetch only."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.connectors.configurable_html import ConfigurableHtmlConnector

BATCH = {
    "mincit-avisos-convocatorias": {
        "url": "https://www.mincit.gov.co/temas-interes/avisos-convocatorias",
        "entity": "MinCIT",
        "country": "Colombia",
        "html": """<html><body><main>
<h1>Avisos convocatorias</h1>
<ul>
<li><a href="/temas-interes/avisos-convocatorias/24-04-2026-aviso-convocatoria-e-inscripciones-4-mi.aspx">Aviso convocatoria e inscripciones entidades facultadas</a></li>
<li><a href="/temas-interes/avisos-convocatorias/aviso-de-convocatoria-resolucion-2117-del-24-de-di.aspx">Aviso convocatoria Resolución 2117 de 2025</a></li>
</ul>
</main></body></html>""",
        "titles": (
            "Aviso convocatoria e inscripciones",
            "Resolución 2117",
        ),
    },
    "eu-tourism-platform-calls": {
        "url": "https://transition-pathways.europa.eu/tourism/funding-and-support/funding-calls",
        "entity": "EU Tourism Platform",
        "country": "European Union",
        "html": """<html><body><main>
<article><h2><a href="/tourism/funding-calls/craft-tour-opens-eu5000-grant-call-craftspeople">CRAFT-TOUR opens grant call for craftspeople</a></h2></article>
<article><h2><a href="/tourism/funding-calls/programme-enhance-tourism-and-promote-sustainable-development-portugal">Programme to enhance tourism in Portugal</a></h2></article>
</main></body></html>""",
        "titles": (
            "CRAFT-TOUR",
            "Portugal",
        ),
    },
    "un-tourism-villages": {
        "url": "https://tourism-villages.unwto.org/en/",
        "entity": "UN Tourism",
        "country": "International",
        "html": """<html><body><main>
<a href="https://tourism-villages.unwto.org/en/the-initiative/">The Best Tourism Villages initiative</a>
<a href="https://tourism-villages.unwto.org/en/upgrade/">Upgrade Programme for villages</a>
</main></body></html>""",
        "titles": (
            "Best Tourism Villages",
            "Upgrade",
        ),
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
async def test_043_parse_fixture(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    meta = BATCH[key]
    mock = AsyncMock(return_value=(meta["url"], meta["html"], "text/html"))
    monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)
    connector = ConfigurableHtmlConnector(
        key,
        meta["url"],
        _seed_config(key),
        entity_name=meta["entity"],
        default_country=meta["country"],
    )
    raw = await connector.fetch()
    candidates = await connector.parse(raw)
    assert len(candidates) >= 1
    titles = {c.title for c in candidates}
    assert any(
        any(expected.lower() in title.lower() for title in titles)
        for expected in meta["titles"]
    ), titles
