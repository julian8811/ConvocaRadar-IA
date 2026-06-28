"""Static analysis tests for the web bundle cleanup.

These tests assert the apps/web code is free of dead dependencies:
- @tanstack/react-table, react-hook-form, zod are NOT declared in
  apps/web/package.json AND are NOT imported from apps/web source.

(plotly.js-dist-min and react-plotly.js were dead when this test
was first written but are now live — the new interactive dashboard
charts import them. The DEAD_DEPS list below reflects only the
remaining packages that still have no consumer.)
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
WEB_ROOT = REPO_ROOT / "apps" / "web"
WEB_PACKAGE_JSON = WEB_ROOT / "package.json"

DEAD_DEPS = (
    "@tanstack/react-table",
    "react-hook-form",
    "zod",
)

SOURCE_DIRS = (
    WEB_ROOT / "app",
    WEB_ROOT / "components",
    WEB_ROOT / "lib",
)


def _load_package_json() -> dict:
    return json.loads(WEB_PACKAGE_JSON.read_text())


def _import_patterns_for(pkg: str) -> tuple[str, ...]:
    """Build the set of import-from regexes that would prove a dep is in use."""
    # escape any regex-meaningful chars in the package name (e.g. @tanstack/, +)
    quoted = re.escape(pkg)
    return (
        rf"from\s+['\"]{quoted}['\"]",
        rf"from\s+['\"]{quoted}/",
        rf"require\(\s*['\"]{quoted}['\"]",
        rf"require\(\s*['\"]{quoted}/",
    )


def _grep_imports_for(pkg: str) -> list[str]:
    """Return the list of (relative_path:line) hits for the package in source dirs."""
    patterns = _import_patterns_for(pkg)
    if not SOURCE_DIRS[0].exists():
        return []
    cmd = [
        "grep",
        "-rEn",
        "(" + ")|(".join(patterns) + ")",
        str(SOURCE_DIRS[0]),
        str(SOURCE_DIRS[1]),
        str(SOURCE_DIRS[2]),
        "--include=*.ts",
        "--include=*.tsx",
        "--include=*.js",
        "--include=*.jsx",
        "--include=*.mjs",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode == 1:
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def test_apps_web_package_json_exists() -> None:
    """Safety net: the test target must be present for the assertions to mean anything."""
    assert WEB_PACKAGE_JSON.exists(), f"Expected {WEB_PACKAGE_JSON}"


def test_dead_deps_absent_from_package_json() -> None:
    """None of the dead deps may be in dependencies or devDependencies."""
    pkg = _load_package_json()
    declared = set(pkg.get("dependencies", {})) | set(pkg.get("devDependencies", {}))
    present = sorted(declared & set(DEAD_DEPS))
    assert not present, (
        f"Dead deps still declared in apps/web/package.json: {present}. "
        "Remove them and run pnpm install to refresh the lockfile."
    )


def test_react_table_not_imported_in_web_source() -> None:
    hits = _grep_imports_for("@tanstack/react-table")
    assert not hits, (
        "@tanstack/react-table is still imported from apps/web source:\n"
        + "\n".join(hits)
    )


def test_react_hook_form_not_imported_in_web_source() -> None:
    hits = _grep_imports_for("react-hook-form")
    assert not hits, (
        "react-hook-form is still imported from apps/web source:\n" + "\n".join(hits)
    )


def test_zod_not_imported_in_web_source() -> None:
    hits = _grep_imports_for("zod")
    assert not hits, (
        "zod is still imported from apps/web source:\n" + "\n".join(hits)
    )
