"""037 more sources batch: eight ConfigurableHtml seeds. AST only."""

from __future__ import annotations

import ast
from pathlib import Path

from app.connectors.configurable_html import HtmlConnectorConfig
from app.connectors.factory import connector_for

BATCH_KEYS = (
    "rhodes-scholarship",
    "knight-hennessy-scholars",
    "gates-cambridge",
    "acumen-fellowship",
    "vliruos-scholarships",
    "twas-opportunities",
    "schmidt-sciences",
    "echoing-green-fellowship",
)

BATCH_URLS = {
    "rhodes-scholarship": "https://www.rhodeshouse.ox.ac.uk/apply/",
    "knight-hennessy-scholars": "https://knight-hennessy.stanford.edu/admission",
    "gates-cambridge": "https://www.gatescambridge.org/apply/",
    "acumen-fellowship": "https://acumen.org/fellowship/",
    "vliruos-scholarships": "https://www.vliruos.be/en/scholarships",
    "twas-opportunities": "https://twas.org/opportunities",
    "schmidt-sciences": "https://www.schmidtsciences.org/opportunities",
    "echoing-green-fellowship": "https://echoinggreen.org/fellowship/",
}

BATCH_COUNTRIES = {
    "rhodes-scholarship": "United Kingdom",
    "knight-hennessy-scholars": "United States",
    "gates-cambridge": "United Kingdom",
    "acumen-fellowship": "International",
    "vliruos-scholarships": "Belgium",
    "twas-opportunities": "International",
    "schmidt-sciences": "United States",
    "echoing-green-fellowship": "United States",
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


def test_037_keys_enabled():
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
    assert len(defs) >= 176


def test_factory_configurable_html_for_037():
    defs = _seed_definitions_by_key()
    for key in BATCH_KEYS:
        connector = connector_for(
            key,
            BATCH_URLS[key],
            "html",
            connector_config=defs[key]["connector_config"],
        )
        assert connector.__class__.__name__ == "ConfigurableHtmlConnector"
