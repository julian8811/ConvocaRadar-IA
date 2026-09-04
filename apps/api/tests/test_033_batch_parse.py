"""033 parse fixtures for Colombia batch 2. Mocked fetch only."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.connectors.configurable_html import ConfigurableHtmlConnector

BATCH = {
    "idartes-pde-portafolio-2026": {
        "url": "https://www.idartes.gov.co/es/convocatorias/estimulos/portafolio-2026",
        "entity": "IDARTES",
        "html": """<html><body><table><tr>
<td>BECA LEP CIRCULACIÓN TEATRAL EN ESPACIO ABIERTO 2026
<a href="https://cultured.gov.co/detalle/convocatorias/3465">Ver convocatoria</a></td>
</tr><tr>
<td>BECA LEP FESTIVALES DE MÚSICA 2026
<a href="https://cultured.gov.co/detalle/convocatorias/3467">Ver convocatoria</a></td>
</tr></table></body></html>""",
        "titles": (
            "BECA LEP CIRCULACIÓN TEATRAL EN ESPACIO ABIERTO 2026",
            "BECA LEP FESTIVALES DE MÚSICA 2026",
        ),
    },
    "fondo-mujer-beneficiarias": {
        "url": "https://fondomujer.gov.co/convocatorias-beneficiarias-fondo-mujer-libre-y-productiva/",
        "entity": "Fondo Mujer",
        "html": """<html><body><main>
<a href="/convocatoria-nacional-fase-2">Convocatoria Nacional Fase 2 – Mujeres</a>
<a href="/convocatorias-para-mujeres">Convocatorias para mujeres</a>
</main></body></html>""",
        "titles": ("Convocatoria Nacional Fase 2 – Mujeres", "Convocatorias para mujeres"),
    },
    "fondo-mujer-proveedores": {
        "url": "https://fondomujer.gov.co/convocatorias-proveedores/",
        "entity": "Fondo Mujer",
        "html": """<html><body><main>
<a href="/convocatoria-proveedores-2026">Convocatoria proveedores 2026</a>
<a href="/convocatorias-cerradas">Convocatorias cerradas</a>
</main></body></html>""",
        "titles": ("Convocatoria proveedores 2026", "Convocatorias cerradas"),
    },
    "bogota-desarrollo-economico": {
        "url": "https://bogota.gov.co/mi-ciudad/desarrollo-economico",
        "entity": "Alcaldía de Bogotá",
        "html": """<html><body>
<a href="/mi-ciudad/desarrollo-economico/bogota-abre-convocatoria-turismo">
  Bogotá abre convocatoria para fortalecer experiencias turísticas</a>
<a href="/mi-ciudad/desarrollo-economico/feria-hogar-2026">
  135 empresas y emprendimientos bogotanos llegan a la Feria del Hogar</a>
</body></html>""",
        "titles": (
            "Bogotá abre convocatoria para fortalecer experiencias turísticas",
            "135 empresas y emprendimientos bogotanos llegan a la Feria del Hogar",
        ),
    },
    "bogota-oportunidades": {
        "url": "https://bogota.gov.co/servicios/oportunidades-y-apoyos",
        "entity": "Alcaldía de Bogotá",
        "html": """<html><body><main>
<a href="/servicios/oportunidades-y-apoyos/estimulos">Estímulos culturales</a>
<a href="/servicios/oportunidades-y-apoyos/empleo">Ofertas de empleo</a>
</main></body></html>""",
        "titles": ("Estímulos culturales", "Ofertas de empleo"),
    },
    "cundinamarca-convocatorias": {
        "url": "https://www.cundinamarca.gov.co/convocatorias",
        "entity": "Gobernación de Cundinamarca",
        "html": """<html><body>
<article><h2><a href="/noticia/acueductos">Más de $6.027 millones permiten mejorar acueductos</a></h2></article>
<article><h2><a href="/noticia/servidores">Gobernación vincula a servidores públicos</a></h2></article>
</body></html>""",
        "titles": (
            "Más de $6.027 millones permiten mejorar acueductos",
            "Gobernación vincula a servidores públicos",
        ),
    },
    "isa-innovacion": {
        "url": "https://www.isa.co/es/innovacion/",
        "entity": "ISA",
        "html": """<html><body>
<article><h2><a href="/es/innovacion/llamado">Innovación hacia un propósito superior</a></h2></article>
<article><h2><a href="/es/noticia/seguridad">Seguridad psicológica</a></h2></article>
</body></html>""",
        "titles": ("Innovación hacia un propósito superior", "Seguridad psicológica"),
    },
    "idrd-convocatorias": {
        "url": "https://www.idrd.gov.co/avisos-de-convocatorias-de-procesos-contractuales-idrd",
        "entity": "IDRD",
        "html": """<html><body><main>
<a href="https://www.colombiacompra.gov.co/secop-ii">Consulta del proceso en SECOP II</a>
<a href="/aviso-segundo-ley-80">Segundo aviso - Ley 80 de 1993</a>
</main></body></html>""",
        "titles": ("Consulta del proceso en SECOP II", "Segundo aviso - Ley 80 de 1993"),
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
async def test_033_parse_fixture(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
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
