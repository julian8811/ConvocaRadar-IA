"""Purge trio 2026-10-18: unwomen-innovate disabled (sólo-convocatorias).

La página fuente de unwomen-innovate es institucional sin convocatorias
(45/45 filas sin fecha ni monto, muestreo prod 2026-10-18). Acuerdo:
deshabilitar la fuente + purgar sus 45 filas. ascun-convocatorias y
cost-open-calls siguen habilitadas (solo purga de filas-noticia/chrome).

RED: falla mientras unwomen-innovate siga habilitada en seed.py.
GREEN: seed la declara con enabled=False.
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


def test_unwomen_innovate_disabled_institutional_no_calls():
    defs = _seed_definitions_by_key()
    assert "unwomen-innovate" in defs, "missing unwomen-innovate"
    assert defs["unwomen-innovate"].get("enabled", True) is False


def test_purge_trio_keeps_ascun_and_cost_enabled():
    # ascun-convocatorias: purga de 67 filas-noticia, fuente habilitada
    # (filtro T2b reject_news ya bloquea nuevas). cost-open-calls: purga
    # de 58 chrome, fuente habilitada (3 calls reales sobreviven).
    defs = _seed_definitions_by_key()
    for key in ("ascun-convocatorias", "cost-open-calls"):
        assert key in defs, f"missing {key}"
        assert defs[key].get("enabled", True) is True, f"{key} must stay enabled"
