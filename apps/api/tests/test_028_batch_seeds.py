"""028 global high-volume seeds: enable WB/DA + six ConfigurableHtml sources.

AST checks only — no live HTTP.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.connectors.configurable_html import HtmlConnectorConfig
from app.connectors.factory import connector_for

ENABLE_KEYS = (
    "world-bank-procurement",
    "developmentaid-tenders",
)

ENABLE_URLS = {
    "world-bank-procurement": "https://search.worldbank.org/api/v2/procnotices",
    "developmentaid-tenders": "https://www.developmentaid.org/tenders_sitemap.xml",
}

ENABLE_TYPES = {
    "world-bank-procurement": "api",
    "developmentaid-tenders": "html",
}

NEW_KEYS = (
    "usa-gov-challenges",
    "fogarty-funding-opps",
    "embo-fellowships",
    "msca-funding",
    "open-society-grants",
    "who-tdr-grants",
)

NEW_URLS = {
    "usa-gov-challenges": "https://www.usa.gov/find-active-challenge",
    "fogarty-funding-opps": (
        "https://www.fic.nih.gov/Funding/Pages/Fogarty-Funding-Opps.aspx"
    ),
    "embo-fellowships": (
        "https://www.embo.org/funding/fellowships-grants-and-career-support/"
    ),
    "msca-funding": "https://marie-sklodowska-curie-actions.ec.europa.eu/funding",
    "open-society-grants": "https://www.opensocietyfoundations.org/grants",
    "who-tdr-grants": "https://tdr.who.int/grants",
}

NEW_DOMAIN_HINTS = {
    "usa-gov-challenges": ("usa.gov",),
    "fogarty-funding-opps": ("fic.nih.gov", "grants.nih.gov"),
    "embo-fellowships": ("embo.org",),
    "msca-funding": ("marie-sklodowska-curie-actions.ec.europa.eu",),
    "open-society-grants": ("opensocietyfoundations.org",),
    "who-tdr-grants": ("tdr.who.int",),
}

CONFIG_FIELDS = (
    "list_selectors",
    "title_selectors",
    "link_selectors",
    "content_selectors",
    "date_labels",
)

REMAINING_ORPHANS = (
    "innovamos-fid",
    "innovamos-global-innovation-fund",
    "finep-brasil",
    "dane-convocatorias",
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


def test_enable_keys_present_enabled_with_urls():
    defs = _seed_definitions_by_key()
    for key in ENABLE_KEYS:
        assert key in defs, f"missing seed definition: {key}"
        definition = defs[key]
        assert definition.get("enabled") is True, f"{key} must be enabled=true"
        assert definition["base_url"] == ENABLE_URLS[key], f"{key} base_url mismatch"
        assert definition["source_type"] == ENABLE_TYPES[key]


def test_new_keys_present_enabled_with_config():
    defs = _seed_definitions_by_key()
    for key in NEW_KEYS:
        assert key in defs, f"missing seed definition: {key}"
        definition = defs[key]
        assert definition.get("enabled", True) is True, f"{key} must be enabled=true"
        assert definition["base_url"] == NEW_URLS[key], f"{key} base_url mismatch"
        assert definition["source_type"] == "html"
        domains = definition.get("allowed_domains") or []
        assert domains, f"{key} needs allowed_domains"
        for hint in NEW_DOMAIN_HINTS[key]:
            assert any(hint in d for d in domains), f"{key} domains missing {hint}"
        config = definition.get("connector_config")
        assert isinstance(config, dict) and config, f"{key} needs connector_config"
        for field in CONFIG_FIELDS:
            assert field in config and config[field], f"{key} missing {field}"
        parsed = HtmlConnectorConfig.from_dict(config)
        assert parsed.list_selectors
        assert parsed.title_selectors
        assert parsed.link_selectors


def test_remaining_orphans_still_disabled():
    defs = _seed_definitions_by_key()
    for key in REMAINING_ORPHANS:
        assert key in defs
        assert defs[key].get("enabled") is False


def test_factory_resolves_enabled_specialized_and_new_html():
    wb = connector_for(
        "world-bank-procurement",
        ENABLE_URLS["world-bank-procurement"],
        source_type="api",
    )
    assert wb.__class__.__name__ == "WorldBankConnector"

    da = connector_for(
        "developmentaid-tenders",
        ENABLE_URLS["developmentaid-tenders"],
        source_type="html",
    )
    assert da.__class__.__name__ == "DevelopmentAidConnector"

    defs = _seed_definitions_by_key()
    usa = connector_for(
        "usa-gov-challenges",
        NEW_URLS["usa-gov-challenges"],
        "html",
        connector_config=defs["usa-gov-challenges"]["connector_config"],
    )
    assert usa.__class__.__name__ == "ConfigurableHtmlConnector"
