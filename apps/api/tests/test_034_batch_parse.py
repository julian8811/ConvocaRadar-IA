"""034 parse fixtures for LatAm batch. Mocked fetch only."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.connectors.configurable_html import ConfigurableHtmlConnector

BATCH = {
    "secihti-mexico-ciencias": {
        "url": "https://secihti.mx/convocatoria_categoria/ciencias-y-humanidades/",
        "entity": "SECIHTI",
        "country": "Mexico",
        "html": """<html><body><main>
<a href="/evento/convocatoria-ciencia-2026">Convocatoria Ciencia Básica 2026</a>
<a href="/evento/humanidades-abierta">Convocatoria Humanidades Abierta</a>
</main></body></html>""",
        "titles": ("Convocatoria Ciencia Básica 2026", "Convocatoria Humanidades Abierta"),
    },
    "secihti-mexico-becas-extranjero": {
        "url": "https://secihti.mx/convocatoria_categoria/becas-al-extranjero/",
        "entity": "SECIHTI",
        "country": "Mexico",
        "html": """<html><body><main>
<a href="/becas-al-extranjero/posgrado-2026">Becas al Extranjero Posgrado 2026</a>
<a href="/evento/estancias-investigacion">Estancias de Investigación en el Extranjero</a>
</main></body></html>""",
        "titles": (
            "Becas al Extranjero Posgrado 2026",
            "Estancias de Investigación en el Extranjero",
        ),
    },
    "segib-noticias": {
        "url": "https://www.segib.org/",
        "entity": "SEGIB",
        "country": "International",
        "html": """<html><body>
<article><h2><a href="/es/memoria-2025">Memoria de 2025: 20 años de la SEGIB</a></h2></article>
<article><h2><a href="/es/premio-compromiso">Premio SEGIB Compromiso Iberoamericano</a></h2></article>
</body></html>""",
        "titles": (
            "Memoria de 2025: 20 años de la SEGIB",
            "Premio SEGIB Compromiso Iberoamericano",
        ),
    },
    "oas-scholarships": {
        "url": "https://www.oas.org/en/scholarships/",
        "entity": "OAS",
        "country": "International",
        "html": """<html><body><main>
<a href="/en/scholarships/Academic_Program.asp">OAS Academic Scholarship Program</a>
<a href="/en/scholarships/brazil.htm">OAS-GCUB Scholarship Program Brazil</a>
</main></body></html>""",
        "titles": (
            "OAS Academic Scholarship Program",
            "OAS-GCUB Scholarship Program Brazil",
        ),
    },
    "fundacion-carolina-becas": {
        "url": "https://fundacioncarolina.es/",
        "entity": "Fundación Carolina",
        "country": "Spain",
        "html": """<html><body><main>
<a href="/convocatoria-de-becas-2026-2027/">Convocatoria de becas 2026-2027</a>
<a href="/formacion/becas/jovenes-lideres/">Becas Jóvenes Líderes Iberoamericanos</a>
</main></body></html>""",
        "titles": (
            "Convocatoria de becas 2026-2027",
            "Becas Jóvenes Líderes Iberoamericanos",
        ),
    },
    "clacso-concursos": {
        "url": "https://www.clacso.org/becas/concursos/",
        "entity": "CLACSO",
        "country": "International",
        "html": """<html><body>
<article><h2><a href="/becas/concurso-ensayo-2026">Concurso de Ensayo CLACSO 2026</a></h2></article>
<article><h2><a href="/becas/beca-investigacion">Beca de Investigación Posdoctoral</a></h2></article>
</body></html>""",
        "titles": ("Concurso de Ensayo CLACSO 2026", "Beca de Investigación Posdoctoral"),
    },
    "agencia-id-argentina": {
        "url": "https://www.argentina.gob.ar/ciencia/agencia",
        "entity": "Agencia I+D+i",
        "country": "Argentina",
        "html": """<html><body><main>
<a href="/noticias/nueva-convocatoria-piicte">Nueva convocatoria PICTE abierta</a>
<a href="/noticias/fondo-argentino">Fondo Argentino Sectorial 2026</a>
</main></body></html>""",
        "titles": ("Nueva convocatoria PICTE abierta", "Fondo Argentino Sectorial 2026"),
    },
    "senacyt-panama": {
        "url": "https://www.senacyt.gob.pa/convocatoriassenacyt/",
        "entity": "SENACYT",
        "country": "Panama",
        "html": """<html><body><main>
<a href="https://www.senacyt.gob.pa/becas-internacionales-e-insercion-de-becarios/">
  Dirección de Desarrollo de Capacidades Científicas y Tecnológicas</a>
<a href="https://www.senacyt.gob.pa/fondos-para-innovacion-y-emprendimiento/">
  Dirección de Innovación Empresarial</a>
<a href="https://www.senacyt.gob.pa/fondos-para-investigacion-cientifica/">
  Dirección de Investigación Científica y Desarrollo Tecnológico</a>
</main></body></html>""",
        "titles": (
            "Dirección de Desarrollo de Capacidades Científicas",
            "Dirección de Innovación Empresarial",
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
async def test_034_parse_fixture(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
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
