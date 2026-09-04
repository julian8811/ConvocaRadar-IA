"""Batch-1 parse fixtures (026: Chile/Peru + IDB/Fulbright). Mocked fetch only — no live HTTP."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.connectors.configurable_html import ConfigurableHtmlConnector
from app.connectors.factory import connector_for

BATCH1 = {
    "anid-concursos": {
        "url": "https://anid.cl/concursos/",
        "country": "Chile",
        "entity": "ANID",
        "html": """<html><body>
<div class="jet-listing-grid__item">
  <a href="https://anid.cl/concursos/concurso-fondecyt-regular-2027/"
     class="jet-engine-listing-overlay-link"></a>
  <h3>Concurso FONDECYT Regular 2027</h3>
  <div>Inicio: 5 de marzo, 2027</div>
  <div>Cierre: 20 de abril, 2027 - 13:00</div>
</div>
<div class="jet-listing-grid__item">
  <h3>Concurso Exploración 2027</h3>
  <div>Cierre: 15 de mayo, 2027</div>
  <a href="https://anid.cl/concursos/concurso-exploracion-2027/">Ver más</a>
</div>
</body></html>""",
        "titles": ("Concurso FONDECYT Regular 2027", "Concurso Exploración 2027"),
    },
    "startup-chile": {
        "url": "https://startupchile.org/postula/",
        "country": "Chile",
        "entity": "Start-Up Chile",
        "html": """<html><body><main class="entry-content">
<h1>Postula a Start-Up Chile</h1>
<p>Aplicaciones abiertas hasta el 30 de junio de 2027.</p>
<p><a href="https://startupchile.org/apply/charly-gen/">Apply via Charly</a></p>
</main></body></html>""",
        "titles": ("Postula a Start-Up Chile",),
    },
    "proinnovate-calendario": {
        "url": "https://calendario.proinnovate.gob.pe/",
        "country": "Peru",
        "entity": "ProInnóvate",
        "html": """<html><body><main><table>
<thead><tr><th>Convocatoria</th><th>Cierre</th></tr></thead>
<tbody>
<tr>
  <td><a href="https://calendario.proinnovate.gob.pe/programa-innova-2027/">Programa Innova PYME 2027</a></td>
  <td>Cierre: 12 de agosto, 2027</td>
</tr>
<tr>
  <td><a href="https://calendario.proinnovate.gob.pe/startup-peru-8/">Startup Perú 8va Gen</a></td>
  <td>Cierre: 1 de septiembre, 2027</td>
</tr>
</tbody>
</table></main></body></html>""",
        "titles": ("Programa Innova PYME 2027", "Startup Perú 8va Gen"),
    },
    "idb-calls-proposals": {
        "url": "https://www.iadb.org/en/how-we-can-work-together/calls-proposals",
        "country": "International",
        "entity": "IDB",
        # Empty open section; eval/closed cards still yield candidates (spec).
        "html": """<html><body><main>
<section class="open-calls"><h2>Open</h2><p>No open calls</p></section>
<article class="card views-row">
  <h3><a href="https://www.iadb.org/en/call/climate-innovation-challenge-2027">
    Climate Innovation Challenge 2027</a></h3>
  <p>Status: Under evaluation</p>
  <p>Deadline: 15 March 2027</p>
</article>
<div class="card">
  <h2><a href="https://www.iadb.org/en/prize/social-impact-prize-2026">
    Social Impact Prize 2026</a></h2>
  <p>Status: Closed</p>
  <p>Closing: 1 December 2026</p>
</div>
</main></body></html>""",
        "titles": (
            "Climate Innovation Challenge 2027",
            "Social Impact Prize 2026",
        ),
    },
    "fulbright-colombia": {
        "url": "https://fulbright.edu.co/",
        "country": "Colombia",
        "entity": "Fulbright Colombia",
        "html": """<html><body><main>
<div class="card elementor-post">
  <h3><a href="https://fulbright.edu.co/convocatoria/beca-investigacion-2027/">
    Beca de Investigación Fulbright 2027</a></h3>
  <p>Cierre: 30 de abril de 2027</p>
</div>
<article class="program">
  <h2><a href="https://fulbright.edu.co/program/foreign-student-program/">
    Foreign Student Program</a></h2>
  <p>Convocatoria Abierta — Deadline: 15 May 2027</p>
</article>
</main></body></html>""",
        "titles": (
            "Beca de Investigación Fulbright 2027",
            "Foreign Student Program",
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
                    for item in ast.literal_eval(stmt.value):
                        if item["key"] == key:
                            return item["connector_config"]
    raise AssertionError(f"connector_config missing for {key}")


@pytest.mark.parametrize("key", list(BATCH1))
def test_connector_for_returns_configurable_html(key: str):
    meta = BATCH1[key]
    connector = connector_for(
        key,
        meta["url"],
        "html",
        entity_name=meta["entity"],
        default_country=meta["country"],
        connector_config=_seed_config(key),
    )
    assert isinstance(connector, ConfigurableHtmlConnector)
    assert connector.source_key == key


@pytest.mark.asyncio
@pytest.mark.parametrize("key", list(BATCH1))
async def test_parse_fixture_yields_candidates(key: str, monkeypatch: pytest.MonkeyPatch):
    meta = BATCH1[key]
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
    assert any(expected in titles for expected in meta["titles"])
    assert mock.await_count >= 1
    # All HTTP goes through the mock — no live network calls.


@pytest.mark.asyncio
async def test_anid_empty_listing_returns_empty(monkeypatch: pytest.MonkeyPatch):
    url = BATCH1["anid-concursos"]["url"]
    empty = "<html><body><p>Sin concursos</p></body></html>"
    mock = AsyncMock(return_value=(url, empty, "text/html"))
    monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)
    connector = ConfigurableHtmlConnector(
        "anid-concursos",
        url,
        _seed_config("anid-concursos"),
        entity_name="ANID",
        default_country="Chile",
    )
    candidates = await connector.parse(await connector.fetch())
    assert candidates == []


@pytest.mark.asyncio
async def test_idb_empty_open_still_parses_eval_closed(
    monkeypatch: pytest.MonkeyPatch,
):
    """Seasonal empty open section must still extract eval/closed cards."""
    meta = BATCH1["idb-calls-proposals"]
    mock = AsyncMock(return_value=(meta["url"], meta["html"], "text/html"))
    monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)
    connector = ConfigurableHtmlConnector(
        "idb-calls-proposals",
        meta["url"],
        _seed_config("idb-calls-proposals"),
        entity_name=meta["entity"],
        default_country=meta["country"],
    )
    candidates = await connector.parse(await connector.fetch())
    assert len(candidates) >= 1
    titles = {c.title for c in candidates}
    assert "Climate Innovation Challenge 2027" in titles or (
        "Social Impact Prize 2026" in titles
    )
