"""Batch-1 convocatoria seed AST checks (026 PR1: Chile + Peru).

Asserts canonical keys, enabled=true, listing URLs, domains, and
non-empty HtmlConnectorConfig shape. No live HTTP.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.connectors.configurable_html import HtmlConnectorConfig

PR1_KEYS = (
    "anid-concursos",
    "startup-chile",
    "proinnovate-calendario",
)

PR1_URLS = {
    "anid-concursos": "https://anid.cl/concursos/",
    "startup-chile": "https://startupchile.org/postula/",
    "proinnovate-calendario": "https://calendario.proinnovate.gob.pe/",
}

PR1_DOMAIN_HINTS = {
    "anid-concursos": ("anid.cl",),
    "startup-chile": ("startupchile.org",),
    "proinnovate-calendario": ("proinnovate.gob.pe",),
}

DEFERRED_KEYS = (
    "corfo",
    "corfo-chile",
    "caf",
    "caf-convocatorias",
    "who-tdr",
    "who-tdr-ops",
)

CONFIG_FIELDS = (
    "list_selectors",
    "title_selectors",
    "link_selectors",
    "content_selectors",
    "date_labels",
)


def _seed_definition_list() -> list[dict]:
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
                    return list(ast.literal_eval(stmt.value))
    raise AssertionError("source_definitions not found in seed_default_sources")


def _seed_definitions_by_key() -> dict[str, dict]:
    return {item["key"]: item for item in _seed_definition_list()}


def test_pr1_keys_present_enabled_with_urls_and_config():
    defs = _seed_definitions_by_key()
    for key in PR1_KEYS:
        assert key in defs, f"missing seed definition: {key}"
        definition = defs[key]
        assert definition.get("enabled", True) is True, f"{key} must be enabled=true"
        assert definition["base_url"] == PR1_URLS[key], f"{key} base_url mismatch"
        assert definition["source_type"] == "html"
        domains = definition.get("allowed_domains") or []
        assert domains, f"{key} needs allowed_domains"
        for hint in PR1_DOMAIN_HINTS[key]:
            assert any(hint in d for d in domains), f"{key} domains missing {hint}"
        config = definition.get("connector_config")
        assert isinstance(config, dict) and config, f"{key} needs connector_config"
        for field in CONFIG_FIELDS:
            assert field in config and config[field], f"{key} missing {field}"
        parsed = HtmlConnectorConfig.from_dict(config)
        assert parsed.list_selectors
        assert parsed.title_selectors
        assert parsed.link_selectors


def test_deferred_and_guard_keys():
    items = _seed_definition_list()
    keys = [item["key"] for item in items]
    defs = {item["key"]: item for item in items}
    for key in DEFERRED_KEYS:
        assert key not in defs, f"deferred key must remain absent: {key}"
    assert "fondecyt-chile" in defs
    fondecyt = defs["fondecyt-chile"]
    assert fondecyt.get("enabled", True) is True
    assert fondecyt.get("connector_config"), "fondecyt-chile must keep connector_config"
    assert "bid-convocatorias" in defs
    bid = defs["bid-convocatorias"]
    assert "procurement" in bid["base_url"]
    for key in PR1_KEYS:
        assert keys.count(key) == 1, f"{key} must appear exactly once"
