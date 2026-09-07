"""Regression guards for bootstrap/shared-source task ownership."""

from __future__ import annotations

import ast
from pathlib import Path


API_DIR = Path(__file__).resolve().parents[1]
RUNNER = API_DIR / "app" / "scraper" / "runner.py"


def _setup_run_source() -> str:
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_setup_run":
            return ast.unparse(node)
    raise AssertionError("_setup_run() not found")


def test_shared_source_task_uses_nullable_organization_not_sentinel() -> None:
    source = _setup_run_source()
    assert "00000000-0000-0000-0000-000000000000" not in source
    assert "organization_id or source.organization_id" in source
