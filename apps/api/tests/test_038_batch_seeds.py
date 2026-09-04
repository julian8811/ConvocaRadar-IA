"""038 Colombia cultura/SINAC batch: eight ConfigurableHtml seeds. AST only."""

from __future__ import annotations

import ast
from pathlib import Path

from app.connectors.configurable_html import HtmlConnectorConfig
from app.connectors.factory import connector_for

BATCH_KEYS = (
    "mincultura-sinac-dashboard",
    "mincultura-sinac-portafolios",
    "mincultura-sinac-avisos",
    "idt-experiencias-2026",
    "idt-noticias",
    "finagro-lec-2026",
    "finagro-beneficiarios",
    "bogota-cultura-recreacion",
)

BATCH_URLS = {
    "mincultura-sinac-dashboard": (
        "https://sistemaconvocatorias.mincultura.gov.co/dashboard"
    ),
    "mincultura-sinac-portafolios": (
        "https://sistemaconvocatorias.mincultura.gov.co/portafolios"
    ),
    "mincultura-sinac-avisos": (
        "https://sistemaconvocatorias.mincultura.gov.co/avisosinformativos"
    ),
    "idt-experiencias-2026": (
        "https://www.idt.gov.co/convocatoria-experiencias-bogota-2026"
    ),
    "idt-noticias": "https://www.idt.gov.co/noticias",
    "finagro-lec-2026": (
        "https://www.finagro.com.co/lineas-especiales-credito-lec-finagro-2026"
    ),
    "finagro-beneficiarios": "https://www.finagro.com.co/beneficiarios",
    "bogota-cultura-recreacion": (
        "https://bogota.gov.co/mi-ciudad/cultura-recreacion-y-deporte"
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


def test_038_keys_enabled_colombia():
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
    assert [k for k, d in defs.items() if d.get("enabled", True) is False] == []
    assert len(defs) >= 184


def test_factory_configurable_html_for_038():
    defs = _seed_definitions_by_key()
    for key in BATCH_KEYS:
        connector = connector_for(
            key,
            BATCH_URLS[key],
            "html",
            connector_config=defs[key]["connector_config"],
        )
        assert connector.__class__.__name__ == "ConfigurableHtmlConnector"
