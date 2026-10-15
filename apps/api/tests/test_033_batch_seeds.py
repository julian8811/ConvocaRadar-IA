"""033 Colombia sources batch 2: eight ConfigurableHtml seeds. AST only."""

from __future__ import annotations

import ast
from pathlib import Path

from app.connectors.configurable_html import HtmlConnectorConfig
from app.connectors.factory import connector_for

BATCH_KEYS = (
    "idartes-pde-portafolio-2026",
    "fondo-mujer-beneficiarias",
    "fondo-mujer-proveedores",
    "bogota-desarrollo-economico",
    "bogota-oportunidades",
    "cundinamarca-convocatorias",
    "isa-innovacion",
    "idrd-convocatorias",
)

BATCH_URLS = {
    "idartes-pde-portafolio-2026": (
        "https://www.idartes.gov.co/es/convocatorias/estimulos/portafolio-2026"
    ),
    "fondo-mujer-beneficiarias": (
        "https://fondomujer.gov.co/convocatorias-beneficiarias-fondo-mujer-libre-y-productiva/"
    ),
    "fondo-mujer-proveedores": "https://fondomujer.gov.co/convocatorias-proveedores/",
    "bogota-desarrollo-economico": "https://bogota.gov.co/mi-ciudad/desarrollo-economico",
    "bogota-oportunidades": "https://bogota.gov.co/servicios/oportunidades-y-apoyos",
    "cundinamarca-convocatorias": "https://www.cundinamarca.gov.co/convocatorias",
    "isa-innovacion": "https://www.isa.co/es/innovacion/",
    "idrd-convocatorias": (
        "https://www.idrd.gov.co/avisos-de-convocatorias-de-procesos-contractuales-idrd"
    ),
}


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


def test_033_keys_enabled_colombia():
    defs = _seed_definitions_by_key()
    for key in BATCH_KEYS:
        assert key in defs, f"missing {key}"
        definition = defs[key]
        assert definition.get("enabled", True) is True
        assert definition["country"] == "Colombia"
        assert definition["base_url"] == BATCH_URLS[key]
        HtmlConnectorConfig.from_dict(definition["connector_config"])


def test_catalog_fully_enabled():
    defs = _seed_definitions_by_key()
    # Deshabilitadas por dictamen: 5 de la tanda 041 (gate X3, issue #62) +
    # idt-noticias (E13) + segib-noticias y cnpq-brasil (auditoría noticieros 2026-10-15; ver test_038/test_034).
    assert {k for k, d in defs.items() if d.get("enabled", True) is False} == {
        "idt-noticias",
        "fontagro-convocatorias",
        "fundacion-biodiversidad-convocatorias",
        "eu-life-calls-cinea",
        "biodiversa-calls",
        "fondo-accion-convocatorias",
        "segib-noticias",
        "cnpq-brasil",
    }
    assert len(defs) >= 144


def test_factory_configurable_html_for_033():
    defs = _seed_definitions_by_key()
    for key in BATCH_KEYS:
        connector = connector_for(
            key,
            BATCH_URLS[key],
            "html",
            connector_config=defs[key]["connector_config"],
        )
        assert connector.__class__.__name__ == "ConfigurableHtmlConnector"
