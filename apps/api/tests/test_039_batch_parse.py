"""039 parse fixtures for 8-source expansion. Mocked fetch only."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.connectors.configurable_html import ConfigurableHtmlConnector

BATCH = {
    "eu-creative-europe-calls": {
        "url": "https://culture.ec.europa.eu/calls",
        "entity": "Creative Europe",
        "html": """<html><body><main>
<article><h2><a href="/calls/call-1">Creative Europe Call for Proposals 2026</a></h2></article>
<article><h2><a href="/calls/call-2">Culture Moves Europe — Mobility Grants</a></h2></article>
</main></body></html>""",
        "titles": ("Creative Europe Call for Proposals 2026", "Culture Moves Europe"),
    },
    "eu-eacea-grants": {
        "url": "https://www.eacea.ec.europa.eu/grants_en",
        "entity": "EACEA",
        "html": """<html><body><main>
<article><h2><a href="/grants/grant-1">EACEA Erasmus+ Grant 2026</a></h2></article>
<article><h2><a href="/grants/grant-2">Creative Europe Culture Grant</a></h2></article>
</main></body></html>""",
        "titles": ("EACEA Erasmus+ Grant 2026", "Creative Europe Culture Grant"),
    },
    "eu-culture-moves-europe": {
        "url": "https://culture.ec.europa.eu/creative-europe/creative-europe-culture-strand/culture-moves-europe",
        "entity": "Culture Moves Europe",
        "html": """<html><body><main>
<article><h2><a href="/culture-moves/call-1">Individual Mobility Action 2026</a></h2></article>
</main></body></html>""",
        "titles": ("Individual Mobility Action 2026",),
    },
    "sicon-bogota-estimulos": {
        "url": "https://sicon.scrd.gov.co/",
        "entity": "SICON SCRD",
        "html": """<html><body><main>
<article><h2><a href="/convocatorias/estimulo-1">Estímulo Arte y Memoria 2026</a></h2></article>
<article><h2><a href="/convocatorias/estimulo-2">Beca de Creación Bogotá</a></h2></article>
</main></body></html>""",
        "titles": ("Estímulo Arte y Memoria 2026", "Beca de Creación Bogotá"),
    },
    "ibermedia-convocatorias": {
        "url": "https://www.programaibermedia.com/convocatorias/",
        "entity": "Ibermedia",
        "html": """<html><body><main>
<article><h2><a href="/convocatorias/desarrollo-2026">Ibermedia Desarrollo 2026</a></h2></article>
</main></body></html>""",
        "titles": ("Ibermedia Desarrollo 2026",),
    },
    "ibermusicas-convocatorias": {
        "url": "https://ibermusicas.org/",
        "entity": "Ibermúsicas",
        "html": """<html><body><main>
<article><h2><a href="/convocatoria-2026">Ibermúsicas Ayudas a la Movilidad 2026</a></h2></article>
</main></body></html>""",
        "titles": ("Ibermúsicas Ayudas a la Movilidad 2026",),
    },
    "eurimages-council-europe": {
        "url": "https://www.coe.int/en/web/eurimages",
        "entity": "Eurimages",
        "html": """<html><body><main>
<article><h2><a href="/eurimages/call-1">Eurimages Co-production Support 2026</a></h2></article>
</main></body></html>""",
        "titles": ("Eurimages Co-production Support 2026",),
    },
    "erasmus-plus-opportunities": {
        "url": "https://erasmus-plus.ec.europa.eu/opportunities/opportunities-for-organisations",
        "entity": "Erasmus+",
        "html": """<html><body><main>
<article><h2><a href="/opportunities/ka2-2026">Erasmus+ KA2 Cooperation Partnerships 2026</a></h2></article>
</main></body></html>""",
        "titles": ("Erasmus+ KA2 Cooperation Partnerships 2026",),
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
async def test_039_parse_fixture(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert len(candidates) >= 1
    titles = {c.title for c in candidates}
    assert any(
        any(expected.lower() in title.lower() for title in titles)
        for expected in meta["titles"]
    ), titles
