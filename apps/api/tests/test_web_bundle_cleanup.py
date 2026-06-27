"""Static analysis tests for the web bundle cleanup.

These tests assert the apps/web code is free of dead dependencies:
- plotly.js-dist-min, react-plotly.js, @tanstack/react-table,
  react-hook-form, zod are NOT declared in apps/web/package.json
- None of those packages are imported from apps/web/app, apps/web/components,
  or apps/web/lib (the only directories that ship in the production bundle)

If any of these checks fail, the corresponding dep is being added back without
a real consumer and is dead weight in the production bundle.
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
    "plotly.js-dist-min",
    "react-plotly.js",
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


def test_plotly_not_imported_in_web_source() -> None:
    hits = _grep_imports_for("plotly.js-dist-min")
    assert not hits, (
        "plotly.js-dist-min (~3.6 MB) is still imported from apps/web source:\n"
        + "\n".join(hits)
    )


def test_react_plotly_not_imported_in_web_source() -> None:
    hits = _grep_imports_for("react-plotly.js")
    assert not hits, (
        "react-plotly.js is still imported from apps/web source:\n" + "\n".join(hits)
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
