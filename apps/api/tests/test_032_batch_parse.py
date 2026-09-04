"""032 parse fixtures for Colombia sources. Mocked fetch only."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.connectors.configurable_html import ConfigurableHtmlConnector

BATCH = {
    "idartes-convocatorias": {
        "url": "https://www.idartes.gov.co/es/convocatorias",
        "entity": "IDARTES",
        "html": """<html><body><main>
<a href="/es/convocatorias/estimulos">Programa Distrital de Estímulos (PDE)</a>
<a href="/es/convocatorias/salas-concertadas">Programa Distrital de Salas Concertadas</a>
</main></body></html>""",
        "titles": (
            "Programa Distrital de Estímulos (PDE)",
            "Programa Distrital de Salas Concertadas",
        ),
    },
    "medellin-desarrollo-economico": {
        "url": "https://www.medellin.gov.co/es/secretaria-desarrollo-economico/",
        "entity": "Alcaldía de Medellín",
        "html": """<html><body>
<a href="/es/sala-de-prensa/noticias/el-distrito-convoca-al-sector-cinematografico">
  El Distrito convoca al sector cinematográfico</a>
<a href="/es/secretaria-desarrollo-economico/banco-de-oportunidades/">
  Banco de las Oportunidades</a>
</body></html>""",
        "titles": (
            "El Distrito convoca al sector cinematográfico",
            "Banco de las Oportunidades",
        ),
    },
    "camara-bucaramanga-programas": {
        "url": "https://www.camaradirecta.com/programas-para-empresarios/",
        "entity": "Cámara de Comercio de Bucaramanga",
        "html": """<html><body>
<a href="/programas-para-empresarios/fortalecimiento/rutaf/">Fortalecimiento</a>
<a href="/programas-para-empresarios/escalamiento/empower/">Escalamiento</a>
</body></html>""",
        "titles": ("Fortalecimiento", "Escalamiento"),
    },
    "fundacion-bolivar-davivienda": {
        "url": "https://www.fundacionbolivardavivienda.org/",
        "entity": "Fundación Bolívar Davivienda",
        "html": """<html><body>
<a href="/programa/aflora">Aflora</a>
<a href="/programa/emprende-pais">Emprende País</a>
</body></html>""",
        "titles": ("Aflora", "Emprende País"),
    },
    "tecnova-convocatorias": {
        "url": "https://tecnnova.org/convocatorias/",
        "entity": "Tecnnova",
        "html": """<html><body>
<a href="/magazine-de-convocatorias-noviembre-2025/">
  Magazine de convocatorias noviembre 2025</a>
<a href="/magazine-de-convocatorias-octubre-2025/">
  Magazine de convocatorias octubre 2025</a>
</body></html>""",
        "titles": (
            "Magazine de convocatorias noviembre 2025",
            "Magazine de convocatorias octubre 2025",
        ),
    },
    "creame-oportunidades": {
        "url": "https://www.creame.com.co/oportunidades",
        "entity": "Creame",
        "html": """<html><body><main>
<a href="/ruta2025">Ruta2025</a>
<a href="/cofrem">Cofrem</a>
</main></body></html>""",
        "titles": ("Ruta2025", "Cofrem"),
    },
    "uniandes-oportunidades-investigacion": {
        "url": "https://investigacioncreacion.uniandes.edu.co/es/oportunidades",
        "entity": "Universidad de los Andes",
        "html": """<html><body>
<a href="https://www.uniandes.edu.co/files/tdr-convocatoria-prisma-semilleros.pdf">
  Términos de referencia</a>
<a href="https://www.uniandes.edu.co/files/tdr-convocatoria-publica-2026.pdf">
  Términos de referencia</a>
</body></html>""",
        "titles": ("Tdr Convocatoria Prisma Semilleros", "Tdr Convocatoria Publica 2026"),
    },
    "fontur-programas": {
        "url": "https://fontur.com.co/",
        "entity": "FONTUR",
        "html": """<html><body>
<a href="/es/programas/red-turistica-de-pueblos-patrimonio">
  Red turística de pueblos patrimonio</a>
<a href="/es/programas/tarjeta-joven-colombia">Tarjeta joven Colombia</a>
</body></html>""",
        "titles": (
            "Red turística de pueblos patrimonio",
            "Tarjeta joven Colombia",
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
async def test_032_parse_fixture(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
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
