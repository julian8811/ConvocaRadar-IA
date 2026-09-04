"""032 Colombia sources: eight ConfigurableHtml seeds. AST only."""

from __future__ import annotations

import ast
from pathlib import Path

from app.connectors.configurable_html import HtmlConnectorConfig
from app.connectors.factory import connector_for

BATCH_KEYS = (
    "idartes-convocatorias",
    "medellin-desarrollo-economico",
    "camara-bucaramanga-programas",
    "fundacion-bolivar-davivienda",
    "tecnova-convocatorias",
    "creame-oportunidades",
    "uniandes-oportunidades-investigacion",
    "fontur-programas",
)

BATCH_URLS = {
    "idartes-convocatorias": "https://www.idartes.gov.co/es/convocatorias",
    "medellin-desarrollo-economico": (
        "https://www.medellin.gov.co/es/secretaria-desarrollo-economico/"
    ),
    "camara-bucaramanga-programas": (
        "https://www.camaradirecta.com/programas-para-empresarios/"
    ),
    "fundacion-bolivar-davivienda": "https://www.fundacionbolivardavivienda.org/",
    "tecnova-convocatorias": "https://tecnnova.org/convocatorias/",
    "creame-oportunidades": "https://www.creame.com.co/oportunidades",
    "uniandes-oportunidades-investigacion": (
        "https://investigacioncreacion.uniandes.edu.co/es/oportunidades"
    ),
    "fontur-programas": "https://fontur.com.co/",
}

CONFIG_FIELDS = (
    "list_selectors",
    "title_selectors",
    "link_selectors",
    "content_selectors",
    "date_labels",
)


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


def test_032_keys_enabled_colombia():
    defs = _seed_definitions_by_key()
    for key in BATCH_KEYS:
        assert key in defs, f"missing {key}"
        definition = defs[key]
        assert definition.get("enabled", True) is True
        assert definition["country"] == "Colombia"
        assert definition["base_url"] == BATCH_URLS[key]
        assert definition["source_type"] == "html"
        config = definition["connector_config"]
        for field in CONFIG_FIELDS:
            assert config.get(field), f"{key} missing {field}"
        HtmlConnectorConfig.from_dict(config)


def test_catalog_fully_enabled():
    defs = _seed_definitions_by_key()
    disabled = [k for k, d in defs.items() if d.get("enabled", True) is False]
    assert disabled == []
    assert len(defs) >= 136


def test_factory_configurable_html_for_032():
    defs = _seed_definitions_by_key()
    for key in BATCH_KEYS:
        connector = connector_for(
            key,
            BATCH_URLS[key],
            "html",
            connector_config=defs[key]["connector_config"],
        )
        assert connector.__class__.__name__ == "ConfigurableHtmlConnector"
