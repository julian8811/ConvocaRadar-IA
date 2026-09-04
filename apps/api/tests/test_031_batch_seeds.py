"""031 foundation/global seeds: eight ConfigurableHtml sources. AST only."""

from __future__ import annotations

import ast
from pathlib import Path

from app.connectors.configurable_html import HtmlConnectorConfig
from app.connectors.factory import connector_for

BATCH_KEYS = (
    "moore-grant-opportunities",
    "mitacs-programs",
    "templeton-funding-areas",
    "mellon-grant-programs",
    "humboldt-sponsorship-programmes",
    "boell-scholarships",
    "fes-studienfoerderung",
    "pronabec-becas",
)

BATCH_URLS = {
    "moore-grant-opportunities": "https://www.moore.org/grant-opportunities",
    "mitacs-programs": "https://www.mitacs.ca/en/programs",
    "templeton-funding-areas": "https://www.templeton.org/funding-areas",
    "mellon-grant-programs": "https://www.mellon.org/grant-programs",
    "humboldt-sponsorship-programmes": (
        "https://www.humboldt-foundation.de/en/apply/sponsorship-programmes"
    ),
    "boell-scholarships": "https://www.boell.de/en/applying-scholarship",
    "fes-studienfoerderung": "https://www.fes.de/studienfoerderung",
    "pronabec-becas": "https://www.pronabec.gob.pe/concursos-becas-creditos/",
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


def test_031_keys_enabled_with_config():
    defs = _seed_definitions_by_key()
    for key in BATCH_KEYS:
        assert key in defs, f"missing {key}"
        definition = defs[key]
        assert definition.get("enabled", True) is True
        assert definition["base_url"] == BATCH_URLS[key]
        assert definition["source_type"] == "html"
        assert definition.get("allowed_domains")
        config = definition["connector_config"]
        for field in CONFIG_FIELDS:
            assert config.get(field), f"{key} missing {field}"
        HtmlConnectorConfig.from_dict(config)


def test_catalog_fully_enabled():
    defs = _seed_definitions_by_key()
    disabled = [k for k, d in defs.items() if d.get("enabled", True) is False]
    assert disabled == []
    assert len(defs) >= 128


def test_factory_configurable_html_for_031():
    defs = _seed_definitions_by_key()
    for key in BATCH_KEYS:
        connector = connector_for(
            key,
            BATCH_URLS[key],
            "html",
            connector_config=defs[key]["connector_config"],
        )
        assert connector.__class__.__name__ == "ConfigurableHtmlConnector"
        assert connector.source_key == key
