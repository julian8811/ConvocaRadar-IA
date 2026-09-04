"""029: reactivated previously-disabled sources — AST + factory checks."""

from __future__ import annotations

import ast
from pathlib import Path

from app.connectors.configurable_html import HtmlConnectorConfig
from app.connectors.factory import connector_for

REACTIVATED = {
    "innpulsa-colombia-startup": {
        "url": (
            "https://convocatorias.innpulsacolombia.com/api/convocatorias"
            "?active_only=true&include_private=false&include_archive=false"
        ),
        "source_type": "api",
        "needs_config": False,
        "connector": "InnpulsaConnector",
    },
    "parlatino-convocatorias": {
        "url": "https://parlatino.org/?s=convocatoria",
        "source_type": "html",
        "needs_config": True,
        "connector": "ConfigurableHtmlConnector",
    },
    "minagricultura-convocatorias": {
        "url": "https://www.minagricultura.gov.co/",
        "source_type": "html",
        "needs_config": True,
        "connector": "ConfigurableHtmlConnector",
    },
    "faperj-brasil": {
        "url": "https://www.faperj.br/?id=28.5.7",
        "source_type": "html",
        "needs_config": True,
        "connector": "ConfigurableHtmlConnector",
    },
    "aecid-espana": {
        "url": "https://www.aecid.es/inicio",
        "source_type": "html",
        "needs_config": True,
        "connector": "ConfigurableHtmlConnector",
    },
    "innovamos-fid": {
        "url": "https://www.innovamos.gov.co/convocatorias",
        "source_type": "html",
        "needs_config": False,
        "connector": "InnovamosConnector",
    },
    "innovamos-global-innovation-fund": {
        "url": "https://www.innovamos.gov.co/convocatorias",
        "source_type": "html",
        "needs_config": False,
        "connector": "InnovamosConnector",
    },
    "finep-brasil": {
        "url": "https://www.finep.gov.br/oportunidades",
        "source_type": "html",
        "needs_config": False,
        "connector": "FinepConnector",
    },
    "dane-convocatorias": {
        "url": (
            "https://www.dane.gov.co/index.php/component/content/category/"
            "275-servicios-al-ciudadano/276-convocatorias-y-contratacion?Itemid=109"
        ),
        "source_type": "html",
        "needs_config": False,
        "connector": "DaneConnector",
    },
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


def test_all_reactivated_keys_enabled_with_urls():
    defs = _seed_definitions_by_key()
    for key, meta in REACTIVATED.items():
        assert key in defs, f"missing {key}"
        definition = defs[key]
        assert definition.get("enabled", True) is True, f"{key} must be enabled"
        assert definition["base_url"] == meta["url"], f"{key} URL mismatch"
        assert definition["source_type"] == meta["source_type"]
        if meta["needs_config"]:
            config = definition.get("connector_config")
            assert isinstance(config, dict) and config
            for field in CONFIG_FIELDS:
                assert config.get(field), f"{key} missing {field}"
            HtmlConnectorConfig.from_dict(config)


def test_no_seed_definition_is_disabled():
    """Catalog health: after 029 reactivation, seed should have zero enabled=False."""
    defs = _seed_definitions_by_key()
    disabled = [k for k, d in defs.items() if d.get("enabled", True) is False]
    assert disabled == [], f"unexpected disabled seeds: {disabled}"


def test_factory_resolves_reactivated_connectors():
    defs = _seed_definitions_by_key()
    for key, meta in REACTIVATED.items():
        kwargs = {}
        if meta["needs_config"]:
            kwargs["connector_config"] = defs[key]["connector_config"]
        connector = connector_for(key, meta["url"], meta["source_type"], **kwargs)
        assert connector.__class__.__name__ == meta["connector"], key
        assert connector.source_key == key
