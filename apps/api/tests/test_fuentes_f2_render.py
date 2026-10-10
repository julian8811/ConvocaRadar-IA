"""F2 (fuentes-cirugia-mayor): flag render opt-in `force_render`/`wait_selector`.

Strict TDD for the opt-in render flag on ``ConfigurableHtmlConnector``:
- default-off: danida-style heavy SSR pages never render unless opted in;
- flag on: render ALWAYS (no <1500 size gate), with optional wait_selector;
- existing ``browser_fallback`` <1500 gate untouched;
- danida-denmark seed carries the flag (AST only, no network).
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock

from app.connectors.configurable_html import ConfigurableHtmlConnector, HtmlConnectorConfig

CONNECTOR_KEY = "test-f2-render"
CONNECTOR_URL = "http://example.com/calls"

VALID_CONFIG: dict = {
    "list_selectors": [".card"],
    "title_selectors": ["h2 a"],
    "link_selectors": ["a[href]"],
    "content_selectors": ["article"],
    "date_labels": ["Deadline:"],
}

# Danida-shaped SSR: heavy page (>1500 chars) with zero calls inside.
HEAVY_SSR_HTML = "<html><body><div class='tabs'>" + "x" * 52000 + "</div></body></html>"
RENDERED_HTML = (
    "<html><body><div class='js-dynamic-list-module'>"
    "<article><h2><a href='/call/1'>Rendered Call One</a></h2></article>"
    "</div></body></html>"
)


def _connector(**overrides):
    config = {**VALID_CONFIG, **overrides}
    return ConfigurableHtmlConnector(CONNECTOR_KEY, CONNECTOR_URL, config)


# ═══════════════════════════════════════════════════════════════
# 1. Config parsing
# ═══════════════════════════════════════════════════════════════


class TestForceRenderConfig:
    def test_defaults_off(self):
        """No flags in dict → force_render False, wait_selector None."""
        config = HtmlConnectorConfig.from_dict(dict(VALID_CONFIG))
        assert config.force_render is False
        assert config.wait_selector is None

    def test_parses_force_render_and_wait_selector(self):
        """Explicit opt-in parses through."""
        config = HtmlConnectorConfig.from_dict(
            {
                **VALID_CONFIG,
                "force_render": True,
                "wait_selector": ".js-dynamic-list-module",
            }
        )
        assert config.force_render is True
        assert config.wait_selector == ".js-dynamic-list-module"


# ═══════════════════════════════════════════════════════════════
# 2. Fetch wiring: force_render renders ALWAYS (no size gate)
# ═══════════════════════════════════════════════════════════════


class TestForceRenderFetch:
    async def test_no_flag_no_render_on_heavy_ssr(self, monkeypatch):
        """RED baseline: danida today — heavy SSR, zero render calls."""
        fetch = AsyncMock(return_value=(CONNECTOR_URL, HEAVY_SSR_HTML, "text/html"))
        render = AsyncMock(return_value=(CONNECTOR_URL, RENDERED_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", fetch)
        monkeypatch.setattr("app.connectors.common.render_page_html", render)

        raw = await _connector().fetch()

        assert render.await_count == 0
        assert raw.content == HEAVY_SSR_HTML

    async def test_force_render_renders_despite_heavy_ssr(self, monkeypatch):
        """Flag on → render_page_html called even with 52KB SSR content."""
        fetch = AsyncMock(return_value=(CONNECTOR_URL, HEAVY_SSR_HTML, "text/html"))
        render = AsyncMock(return_value=(CONNECTOR_URL, RENDERED_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", fetch)
        monkeypatch.setattr("app.connectors.common.render_page_html", render)

        raw = await _connector(force_render=True).fetch()

        assert render.await_count == 1
        assert raw.content == RENDERED_HTML

    async def test_force_render_passes_wait_selector(self, monkeypatch):
        """wait_selector reaches render_page_html."""
        fetch = AsyncMock(return_value=(CONNECTOR_URL, HEAVY_SSR_HTML, "text/html"))
        render = AsyncMock(return_value=(CONNECTOR_URL, RENDERED_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", fetch)
        monkeypatch.setattr("app.connectors.common.render_page_html", render)

        await _connector(
            force_render=True, wait_selector=".js-dynamic-list-module"
        ).fetch()

        _, kwargs = render.call_args
        assert kwargs.get("wait_selector") == ".js-dynamic-list-module"

    async def test_force_render_without_wait_selector(self, monkeypatch):
        """Flag on without wait_selector → render with wait_selector=None."""
        fetch = AsyncMock(return_value=(CONNECTOR_URL, HEAVY_SSR_HTML, "text/html"))
        render = AsyncMock(return_value=(CONNECTOR_URL, RENDERED_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", fetch)
        monkeypatch.setattr("app.connectors.common.render_page_html", render)

        raw = await _connector(force_render=True).fetch()

        assert render.await_count == 1
        _, kwargs = render.call_args
        assert kwargs.get("wait_selector") is None
        assert raw.content == RENDERED_HTML

    async def test_force_render_failure_keeps_httpx_content(self, monkeypatch):
        """Render blowing up must not break the fetch — keep SSR content."""
        fetch = AsyncMock(return_value=(CONNECTOR_URL, HEAVY_SSR_HTML, "text/html"))
        render = AsyncMock(side_effect=RuntimeError("no chromium"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", fetch)
        monkeypatch.setattr("app.connectors.common.render_page_html", render)

        raw = await _connector(force_render=True).fetch()

        assert raw.content == HEAVY_SSR_HTML


# ═══════════════════════════════════════════════════════════════
# 3. browser_fallback <1500 gate intact
# ═══════════════════════════════════════════════════════════════


class TestBrowserFallbackGateIntact:
    async def test_small_shell_still_renders(self, monkeypatch):
        """browser_fallback + tiny shell → render (pre-existing behavior)."""
        fetch = AsyncMock(return_value=(CONNECTOR_URL, "<html>x</html>", "text/html"))
        render = AsyncMock(return_value=(CONNECTOR_URL, RENDERED_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", fetch)
        monkeypatch.setattr("app.connectors.common.render_page_html", render)

        raw = await _connector(browser_fallback=True).fetch()

        assert render.await_count == 1
        assert raw.content == RENDERED_HTML

    async def test_heavy_ssr_still_skips_fallback(self, monkeypatch):
        """browser_fallback + heavy SSR → NO render (gate <1500 intact)."""
        fetch = AsyncMock(return_value=(CONNECTOR_URL, HEAVY_SSR_HTML, "text/html"))
        render = AsyncMock(return_value=(CONNECTOR_URL, RENDERED_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", fetch)
        monkeypatch.setattr("app.connectors.common.render_page_html", render)

        raw = await _connector(browser_fallback=True).fetch()

        assert render.await_count == 0
        assert raw.content == HEAVY_SSR_HTML

    async def test_both_flags_heavy_ssr_renders(self, monkeypatch):
        """force_render wins over the size gate when both flags are on."""
        fetch = AsyncMock(return_value=(CONNECTOR_URL, HEAVY_SSR_HTML, "text/html"))
        render = AsyncMock(return_value=(CONNECTOR_URL, RENDERED_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", fetch)
        monkeypatch.setattr("app.connectors.common.render_page_html", render)

        raw = await _connector(browser_fallback=True, force_render=True).fetch()

        assert render.await_count == 1
        assert raw.content == RENDERED_HTML


# ═══════════════════════════════════════════════════════════════
# 4. danida-denmark seed carries the flag (AST only)
# ═══════════════════════════════════════════════════════════════


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


class TestDanidaSeed:
    def test_danida_has_force_render_config(self):
        """danida-denmark opts into render with a list-module wait selector."""
        danida = _seed_definitions_by_key()["danida-denmark"]
        config = danida.get("connector_config")
        assert isinstance(config, dict), "danida needs connector_config for F2"
        assert config.get("force_render") is True
        assert config.get("wait_selector") == ".js-dynamic-list-module"
        # Config must validate through the real dataclass parser.
        parsed = HtmlConnectorConfig.from_dict(config)
        assert parsed.force_render is True

    def test_danida_points_at_calls_list_page(self):
        """Seed URL is the DynamicWeb list page, not the landing."""
        danida = _seed_definitions_by_key()["danida-denmark"]
        assert "calls-for-proposals" in danida["base_url"]
