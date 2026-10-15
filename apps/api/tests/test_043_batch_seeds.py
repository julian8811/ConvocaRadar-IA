"""043 tourism expansion: three seeds (MinCIT avisos, EU platform, UN BTV). AST only."""

from __future__ import annotations

import ast
from pathlib import Path

from app.connectors.configurable_html import HtmlConnectorConfig
from app.connectors.factory import connector_for

BATCH_KEYS = (
    "mincit-avisos-convocatorias",
    "eu-tourism-platform-calls",
    "un-tourism-villages",
)

BATCH_URLS = {
    "mincit-avisos-convocatorias": (
        "https://www.mincit.gov.co/temas-interes/avisos-convocatorias"
    ),
    "eu-tourism-platform-calls": (
        "https://transition-pathways.europa.eu/tourism/funding-and-support/funding-calls"
    ),
    "un-tourism-villages": "https://tourism-villages.unwto.org/en/",
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


def test_043_keys_enabled():
    defs = _seed_definitions_by_key()
    for key in BATCH_KEYS:
        assert key in defs, f"missing {key}"
        definition = defs[key]
        assert definition.get("enabled", True) is True, f"{key} must be enabled"
        assert definition["base_url"] == BATCH_URLS[key]
        HtmlConnectorConfig.from_dict(definition["connector_config"])


def test_043_countries():
    defs = _seed_definitions_by_key()
    assert defs["mincit-avisos-convocatorias"]["country"] == "Colombia"
    assert defs["eu-tourism-platform-calls"]["country"] == "European Union"
    assert defs["un-tourism-villages"]["country"] == "International"


def test_factory_configurable_html_for_043():
    defs = _seed_definitions_by_key()
    for key in BATCH_KEYS:
        connector = connector_for(
            key,
            BATCH_URLS[key],
            "html",
            connector_config=defs[key]["connector_config"],
        )
        assert connector.__class__.__name__ == "ConfigurableHtmlConnector"
