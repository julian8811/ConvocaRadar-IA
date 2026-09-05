"""038 parse fixtures for Colombia cultura/SINAC batch. Mocked fetch only."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.connectors.configurable_html import ConfigurableHtmlConnector

BATCH = {
    "mincultura-sinac-dashboard": {
        "url": "https://sistemaconvocatorias.mincultura.gov.co/dashboard",
        "entity": "MinCultura SINAC",
        "html": """<html><body><main>
<a href="/verConvocatoria/1301">Jóvenes por el Cambio 2026</a>
<a href="/verConvocatoria/1295">Beca a proyectos culturales de la diáspora colombiana</a>
</main></body></html>""",
        "titles": (
            "Jóvenes por el Cambio 2026",
            "Beca a proyectos culturales de la diáspora colombiana",
        ),
    },
    "mincultura-sinac-portafolios": {
        "url": "https://sistemaconvocatorias.mincultura.gov.co/portafolios",
        "entity": "MinCultura SINAC",
        "html": """<html><body><main>
<a href="/programas/3">Portafolio del Programa Nacional de Estímulos</a>
<a href="/programas/11">Convocatoria Jóvenes por el Cambio</a>
</main></body></html>""",
        "titles": (
            "Portafolio del Programa Nacional de Estímulos",
            "Convocatoria Jóvenes por el Cambio",
        ),
    },
    "mincultura-sinac-avisos": {
        "url": "https://sistemaconvocatorias.mincultura.gov.co/avisosinformativos",
        "entity": "MinCultura SINAC",
        "html": """<html><body><main>
<a href="/avisos/beca-bibliotecas-1">1 Beca para el fortalecimiento de bibliotecas públicas</a>
<a href="/avisos/beca-bibliotecas-2">2 Beca para el fortalecimiento de bibliotecas públicas</a>
</main></body></html>""",
        "titles": (
            "Beca para el fortalecimiento de bibliotecas públicas",
            "Beca para el fortalecimiento de bibliotecas públicas",
        ),
    },
    "idt-experiencias-2026": {
        "url": "https://www.idt.gov.co/convocatoria-experiencias-bogota-2026",
        "entity": "IDT",
        "html": """<html><body><main>
<a href="/files/terminos-referencia.pdf">Descargar PDF: Términos de Referencia</a>
<a href="/files/carta-compromiso.pdf">Descargar PDF: Carta de Compromiso</a>
</main></body></html>""",
        "titles": ("Términos de Referencia", "Carta de Compromiso"),
    },
    "idt-noticias": {
        "url": "https://www.idt.gov.co/noticias",
        "entity": "IDT",
        "html": """<html><body>
<article><h2><a href="/noticias/conectividad">Bogotá crece en conectividad turística</a></h2></article>
<article><h2><a href="/noticias/costa-rica">Bogotá impulsa su oferta turística en Costa Rica</a></h2></article>
</body></html>""",
        "titles": (
            "Bogotá crece en conectividad turística",
            "Bogotá impulsa su oferta turística en Costa Rica",
        ),
    },
    "finagro-lec-2026": {
        "url": "https://www.finagro.com.co/lineas-especiales-credito-lec-finagro-2026",
        "entity": "FINAGRO",
        "html": """<html><body><main>
<a href="/credito-sostenible">Crédito Sostenible</a>
<a href="/lineas-especiales-credito-lec-finagro-2026">Líneas Especiales de Crédito LEC</a>
</main></body></html>""",
        "titles": ("Crédito Sostenible", "Líneas Especiales de Crédito LEC"),
    },
    "finagro-beneficiarios": {
        "url": "https://www.finagro.com.co/beneficiarios",
        "entity": "FINAGRO",
        "html": """<html><body><main>
<a href="/credito-agropecuario">Crédito agropecuario</a>
<a href="/microcredito-rural">Microcrédito rural</a>
</main></body></html>""",
        "titles": ("Crédito agropecuario", "Microcrédito rural"),
    },
    "bogota-cultura-recreacion": {
        "url": "https://bogota.gov.co/mi-ciudad/cultura-recreacion-y-deporte",
        "entity": "Alcaldía de Bogotá",
        "html": """<html><body><main>
<a href="/mi-ciudad/cultura-recreacion-y-deporte/convocatoria-estimulos">
Convocatoria de estímulos culturales</a>
<a href="/mi-ciudad/cultura-recreacion-y-deporte/agenda-cultural">Agenda cultural de Bogotá</a>
</main></body></html>""",
        "titles": ("Convocatoria de estímulos culturales", "Agenda cultural de Bogotá"),
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
async def test_038_parse_fixture(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    meta = BATCH[key]
    mock = AsyncMock(return_value=(meta["url"], meta["html"], "text/html"))
    monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)
    connector = ConfigurableHtmlConnector(
        key,
        meta["url"],
        _seed_config(key),
        entity_name=meta["entity"],
        default_country="Colombia",
    )
    raw = await connector.fetch()
    candidates = await connector.parse(raw)
    assert len(candidates) >= 1
    titles = {c.title for c in candidates}
    assert any(
        any(expected.lower() in title.lower() for title in titles)
        for expected in meta["titles"]
    ), titles
