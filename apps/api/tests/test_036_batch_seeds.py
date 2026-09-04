"""036 more global sources batch: eight ConfigurableHtml seeds. AST only."""

from __future__ import annotations

import ast
from pathlib import Path

from app.connectors.configurable_html import HtmlConnectorConfig
from app.connectors.factory import connector_for

BATCH_KEYS = (
    "nuffic-scholarships",
    "nz-manaaki-scholarships",
    "owsd-fellowships",
    "ashoka-fellowship",
    "erc-grants",
    "simons-funding",
    "sloan-grants",
    "climateworks-programs",
)

BATCH_URLS = {
    "nuffic-scholarships": "https://www.nuffic.nl/en/subjects/scholarships",
    "nz-manaaki-scholarships": (
        "https://www.mfat.govt.nz/en/aid-and-development/new-zealand-government-scholarships"
    ),
    "owsd-fellowships": "https://owsd.net/career-development/phd-fellowship",
    "ashoka-fellowship": "https://www.ashoka.org/en-us/program/ashoka-fellowship",
    "erc-grants": "https://erc.europa.eu/apply-grant",
    "simons-funding": "https://www.simonsfoundation.org/funding-opportunities/",
    "sloan-grants": "https://sloan.org/grants/apply",
    "climateworks-programs": "https://www.climateworks.org/programs/",
}

BATCH_COUNTRIES = {
    "nuffic-scholarships": "Netherlands",
    "nz-manaaki-scholarships": "New Zealand",
    "owsd-fellowships": "International",
    "ashoka-fellowship": "International",
    "erc-grants": "European Union",
    "simons-funding": "United States",
    "sloan-grants": "United States",
    "climateworks-programs": "International",
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


def test_036_keys_enabled():
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
    assert len(defs) >= 168


def test_factory_configurable_html_for_036():
    defs = _seed_definitions_by_key()
    for key in BATCH_KEYS:
        connector = connector_for(
            key,
            BATCH_URLS[key],
            "html",
            connector_config=defs[key]["connector_config"],
        )
        assert connector.__class__.__name__ == "ConfigurableHtmlConnector"
