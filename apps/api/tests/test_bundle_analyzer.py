"""Task 3 — Verify @next/bundle-analyzer setup.

Checks that:
1. @next/bundle-analyzer is listed as a devDependency in web/package.json
2. An "analyze" script exists that sets ANALYZE=true
3. next.config.ts imports and wraps with withBundleAnalyzer
"""

from __future__ import annotations

import json
from pathlib import Path


WEB_DIR = Path(__file__).resolve().parents[3] / "apps" / "web"


def test_bundle_analyzer_is_dev_dependency() -> None:
    """@next/bundle-analyzer must be a devDependency."""
    pkg = json.loads((WEB_DIR / "package.json").read_text(encoding="utf-8"))
    deps = pkg.get("devDependencies", {})
    assert "@next/bundle-analyzer" in deps, (
        "@next/bundle-analyzer must be listed in devDependencies of apps/web/package.json"
    )


def test_analyze_script_exists() -> None:
    """An 'analyze' script must exist that sets ANALYZE=true."""
    pkg = json.loads((WEB_DIR / "package.json").read_text(encoding="utf-8"))
    scripts = pkg.get("scripts", {})
    analyze_script = scripts.get("analyze", "")
    assert "ANALYZE=true" in analyze_script or "ANALYZE=true" in analyze_script, (
        f"Expected 'analyze' script to set ANALYZE=true, got: {analyze_script!r}"
    )
    assert "next build" in analyze_script, (
        f"Expected 'analyze' script to run next build, got: {analyze_script!r}"
    )


def test_next_config_imports_bundle_analyzer() -> None:
    """next.config.ts must import @next/bundle-analyzer and wrap the config."""
    config_path = WEB_DIR / "next.config.ts"
    assert config_path.exists(), f"Expected {config_path} to exist"
    source = config_path.read_text(encoding="utf-8")
    assert "withBundleAnalyzer" in source or "@next/bundle-analyzer" in source, (
        "next.config.ts must import from @next/bundle-analyzer"
    )
    assert "withBundleAnalyzer" in source, (
        "The config must be wrapped with withBundleAnalyzer()"
    )
