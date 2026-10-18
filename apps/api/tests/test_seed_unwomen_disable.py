"""Disable zero-yield sources (T1/T2 2026-10-18, sólo-convocatorias).

- unwomen-innovate: institucional sin convocatorias (45/45 filas, purge trio).
- ascun-convocatorias: feed 100% noticias (200 parsed/0 válidos tras filtro T2b).
- dane-convocatorias, idb-calls-proposals, sicon-bogota-estimulos: 0 filas
  + last_item_count=0 + consecutive_empty_runs=5 (T1).
- cost-open-calls sigue habilitada (3 calls reales sobreviven a su purga).

RED: falla mientras alguna de las 4 siga habilitada en seed.py.
GREEN: seed las declara con enabled=False.
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


_DISABLED_ZERO_YIELD = (
    "unwomen-innovate",
    "ascun-convocatorias",
    "dane-convocatorias",
    "idb-calls-proposals",
    "sicon-bogota-estimulos",
)


def test_unwomen_innovate_disabled_institutional_no_calls():
    defs = _seed_definitions_by_key()
    assert "unwomen-innovate" in defs, "missing unwomen-innovate"
    assert defs["unwomen-innovate"].get("enabled", True) is False


def test_zero_yield_sources_disabled():
    defs = _seed_definitions_by_key()
    for key in _DISABLED_ZERO_YIELD:
        assert key in defs, f"missing {key}"
        assert defs[key].get("enabled", True) is False, f"{key} must be disabled"


def test_purge_trio_keeps_cost_enabled():
    # cost-open-calls: purga de 58 chrome, fuente habilitada
    # (3 calls reales sobreviven).
    defs = _seed_definitions_by_key()
    assert "cost-open-calls" in defs, "missing cost-open-calls"
    assert defs["cost-open-calls"].get("enabled", True) is True
