"""Orphan seed wiring + factory World Bank registration (PR4 / 025 / 028).

Factory must side-effect-import world_bank so ``connector_for`` resolves the
registered class without the caller importing the connector module first.
Four orphan source definitions remain with ``enabled=False`` (WB + DevelopmentAid
were enabled in 028).
"""

from __future__ import annotations

import ast
from pathlib import Path

ORPHAN_KEYS = (
    "innovamos-fid",
    "innovamos-global-innovation-fund",
    "finep-brasil",
    "dane-convocatorias",
)

ORPHAN_URLS = {
    "innovamos-fid": "https://www.innovamos.gov.co/convocatorias",
    "innovamos-global-innovation-fund": "https://www.innovamos.gov.co/convocatorias",
    "finep-brasil": "https://www.finep.gov.br/oportunidades",
    "dane-convocatorias": (
        "https://www.dane.gov.co/index.php/component/content/category/"
        "275-servicios-al-ciudadano/276-convocatorias-y-contratacion?Itemid=109"
    ),
}


def _seed_definitions_by_key() -> dict[str, dict]:
    """Parse ``source_definitions`` literals from ``seed_default_sources``."""
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
                    defs = ast.literal_eval(stmt.value)
                    return {item["key"]: item for item in defs}
    raise AssertionError("source_definitions not found in seed_default_sources")


def test_factory_returns_world_bank_without_test_importing_world_bank_module():
    """connector_for must resolve WorldBank via factory side-effect import.

    This file intentionally does NOT import ``app.connectors.world_bank``.
    """
    from app.connectors.factory import connector_for

    connector = connector_for(
        "world-bank-procurement",
        "https://search.worldbank.org/api/v2/procnotices",
        source_type="api",
    )
    assert connector.__class__.__module__ == "app.connectors.world_bank"
    assert connector.__class__.__name__ == "WorldBankConnector"
    assert connector.source_key == "world-bank-procurement"


def test_factory_source_imports_world_bank_for_register_side_effect():
    factory_path = Path(__file__).resolve().parents[1] / "app" / "connectors" / "factory.py"
    source = factory_path.read_text(encoding="utf-8")
    assert "from app.connectors.world_bank import" in source
    assert "WorldBankConnector" in source


def test_orphan_seed_definitions_exist_disabled_with_expected_urls():
    defs = _seed_definitions_by_key()
    for key in ORPHAN_KEYS:
        assert key in defs, f"missing orphan seed definition: {key}"
        definition = defs[key]
        assert definition.get("enabled") is False, f"{key} must be enabled=False"
        assert definition["base_url"] == ORPHAN_URLS[key], f"{key} base_url mismatch"
        assert definition["source_type"] in {"api", "html"}
        assert definition.get("allowed_domains"), f"{key} needs allowed_domains"
