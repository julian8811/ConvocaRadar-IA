"""035 global funding+training batch: eight ConfigurableHtml seeds. AST only."""

from __future__ import annotations

import ast
from pathlib import Path

from app.connectors.configurable_html import HtmlConnectorConfig
from app.connectors.factory import connector_for

BATCH_KEYS = (
    "commonwealth-scholarships",
    "unitar-courses",
    "educationusa-scholarships",
    "iie-programs",
    "macarthur-programs",
    "mext-scholarships",
    "worldbank-scholarships",
    "amazon-research-awards",
)

BATCH_URLS = {
    "commonwealth-scholarships": "https://cscuk.fcdo.gov.uk/scholarships/",
    "unitar-courses": "https://www.unitar.org/courses",
    "educationusa-scholarships": "https://educationusa.state.gov/find-financial-aid",
    "iie-programs": "https://www.iie.org/programs/",
    "macarthur-programs": "https://www.macfound.org/programs/",
    "mext-scholarships": "https://www.studyinjapan.go.jp/en/planning/scholarship/",
    "worldbank-scholarships": "https://www.worldbank.org/en/programs/scholarships",
    "amazon-research-awards": "https://www.amazon.science/research-awards",
}

BATCH_COUNTRIES = {
    "commonwealth-scholarships": "United Kingdom",
    "unitar-courses": "International",
    "educationusa-scholarships": "United States",
    "iie-programs": "United States",
    "macarthur-programs": "United States",
    "mext-scholarships": "Japan",
    "worldbank-scholarships": "International",
    "amazon-research-awards": "United States",
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


def test_035_keys_enabled_global():
    defs = _seed_definitions_by_key()
    for key in BATCH_KEYS:
        assert key in defs, f"missing {key}"
        definition = defs[key]
        assert definition.get("enabled", True) is True
        assert definition["country"] == BATCH_COUNTRIES[key]
        assert definition["base_url"] == BATCH_URLS[key]
        HtmlConnectorConfig.from_dict(definition["connector_config"])


def test_catalog_fully_enabled():
    defs = _seed_definitions_by_key()
    assert [k for k, d in defs.items() if d.get("enabled", True) is False] == []
    assert len(defs) >= 160


def test_factory_configurable_html_for_035():
    defs = _seed_definitions_by_key()
    for key in BATCH_KEYS:
        connector = connector_for(
            key,
            BATCH_URLS[key],
            "html",
            connector_config=defs[key]["connector_config"],
        )
        assert connector.__class__.__name__ == "ConfigurableHtmlConnector"
