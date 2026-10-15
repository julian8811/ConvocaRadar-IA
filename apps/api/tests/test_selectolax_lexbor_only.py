"""Regression pin: Modest backend must never come back (incident 2026-10-09).

On 2026-10-09 a minciencias run failed with "Modest backend is deprecated
since selectolax 1.0" because the deployed image predated the lexbor
migration (9e0aecb). All parsing must go through ``selectolax.lexbor``;
this test fails if anyone reintroduces a Modest import.
"""

from __future__ import annotations

import ast
from pathlib import Path


def test_no_modest_backend_imports():
    roots = [
        Path(__file__).resolve().parents[1] / "app",
        Path(__file__).resolve().parents[2] / "scripts",
    ]
    offenders: list[str] = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("selectolax"):
                    if (node.module or "") != "selectolax.lexbor":
                        offenders.append(f"{path}:{node.lineno}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("selectolax.") and alias.name != "selectolax.lexbor":
                            offenders.append(f"{path}:{node.lineno}")
    assert offenders == [], f"non-lexbor selectolax imports: {offenders}"
