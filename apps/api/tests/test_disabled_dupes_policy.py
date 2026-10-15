"""Policy pin: grants-gov-rss stays disabled (pure duplicate intake).

Evidence 2026-10-15 (prod, 30d): 449 found / 0 created; all 24 stored rows
duplicated under grants-gov / simpler-grants. The RSS feed adds zero new
calls — it only burns sweep budget re-ingesting the same NIH items.
"""

from __future__ import annotations

import ast
from pathlib import Path


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


def test_grants_gov_rss_disabled_duplicate_intake():
    defs = _seed_definitions_by_key()
    assert defs["grants-gov-rss"].get("enabled", True) is False
