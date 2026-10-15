"""Monitoreo diario total: toda fuente habilitada corre a cadencia diaria.

Decisión 2026-10-15 (odd/tasks/monitoreo-diario-fuentes.md): el usuario
requiere monitoreo diario de TODAS las fuentes; los recortes de frecuencia
quedan prohibidos. Las deshabilitadas por dictamen conservan su frecuencia
(gate X3 de la tanda 041 y pines de noticieros).
"""

from __future__ import annotations

import ast
from pathlib import Path


def _seed_definitions() -> list[dict]:
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
                    return [item for item in ast.literal_eval(stmt.value)]
    raise AssertionError("source_definitions not found")


def test_all_enabled_sources_daily():
    defs = _seed_definitions()
    non_daily = sorted(
        d["key"] for d in defs
        if d.get("enabled", True) is not False
        and d.get("scraping_frequency", "daily") != "daily"
    )
    assert non_daily == [], f"fuentes habilitadas no-diarias: {non_daily}"


def test_disabled_keep_their_frequency():
    defs = {d["key"]: d for d in _seed_definitions()}
    for key in (
        "fontagro-convocatorias",
        "fundacion-biodiversidad-convocatorias",
        "eu-life-calls-cinea",
        "biodiversa-calls",
        "fondo-accion-convocatorias",
    ):
        assert defs[key].get("scraping_frequency") == "weekly", key
