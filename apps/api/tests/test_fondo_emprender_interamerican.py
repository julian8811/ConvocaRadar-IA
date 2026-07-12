"""Tests for Fondo Emprender SENA + Inter-American Foundation connectors.

Both sources are HTML-based with declarative connector_config that routes
them to ConfigurableHtmlConnector. These tests verify:
  1. The config dicts parse correctly into HtmlConnectorConfig.
  2. The factory connector_for() returns ConfigurableHtmlConnector.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.connectors.base import RawSourceResult
from app.connectors.configurable_html import ConfigurableHtmlConnector

# ── Fondo Emprender SENA ─────────────────────────────────────────────────

FONDO_KEY = "fondo-emprender-sena"
FONDO_URL = (
    "https://www.fondoemprender.com/SitePages/FondoEmprenderConvocatoriasVigentes.aspx"
)

FONDO_CONFIG: dict = {
    "list_selectors": ["div.row"],
    "title_selectors": ["a", "h2", "h3"],
    "link_selectors": ["a[href*='Conv']"],
    "content_selectors": ["article", ".page-content", "main"],
    "date_labels": ["Fecha de cierre:", "Cierre:", "Deadline:"],
    "detail_enrichment": True,
}

# ── Inter-American Foundation ────────────────────────────────────────────

IAF_KEY = "interamerican-foundation"
IAF_URL = "https://iaf.gov/grants/"

IAF_CONFIG: dict = {
    "list_selectors": ["article"],
    "title_selectors": ["h2", "h2 a", "h3 a"],
    "link_selectors": ["a"],
    "content_selectors": ["article", "main", ".entry-content"],
    "date_labels": ["Deadline:", "Application Deadline:", "Due:"],
    "detail_enrichment": True,
}


# ═══════════════════════════════════════════════════════════════════════
# Fondo Emprender SENA tests
# ═══════════════════════════════════════════════════════════════════════


class TestFondoEmprenderConfig:
    """Fondo Emprender connector_config is valid."""

    def test_config_is_valid(self):
        """Fondo Emprender config dict parses correctly into HtmlConnectorConfig."""
        from app.connectors.configurable_html import HtmlConnectorConfig

        config = HtmlConnectorConfig.from_dict(FONDO_CONFIG)
        assert config.list_selectors == ["div.row"]
        assert config.title_selectors == ["a", "h2", "h3"]
        assert config.link_selectors == ["a[href*='Conv']"]
        assert "Cierre:" in config.date_labels
        assert config.detail_enrichment is True

    def test_connector_for_returns_configurable_html(self):
        """connector_for with fondo-emprender-sena returns ConfigurableHtmlConnector."""
        from app.connectors.factory import connector_for

        connector = connector_for(
            FONDO_KEY,
            FONDO_URL,
            "html",
            entity_name="Fondo Emprender SENA",
            default_country="Colombia",
            connector_config=FONDO_CONFIG,
        )
        assert isinstance(connector, ConfigurableHtmlConnector)
        assert connector.source_key == FONDO_KEY

    def test_connector_for_no_config_falls_back_to_generic_html(self):
        """Without connector_config, factory falls back to GenericHtmlConnector."""
        from app.connectors.factory import connector_for
        from app.connectors.generic_html import GenericHtmlConnector

        connector = connector_for(
            FONDO_KEY,
            FONDO_URL,
            "html",
        )
        assert isinstance(connector, GenericHtmlConnector)


# ═══════════════════════════════════════════════════════════════════════
# Inter-American Foundation tests
# ═══════════════════════════════════════════════════════════════════════


class TestInteramericanConfig:
    """Inter-American Foundation connector_config is valid."""

    def test_config_is_valid(self):
        """IAF config dict parses correctly into HtmlConnectorConfig."""
        from app.connectors.configurable_html import HtmlConnectorConfig

        config = HtmlConnectorConfig.from_dict(IAF_CONFIG)
        assert config.list_selectors == ["article"]
        assert config.title_selectors == ["h2", "h2 a", "h3 a"]
        assert config.link_selectors == ["a"]
        assert "Deadline:" in config.date_labels
        assert config.detail_enrichment is True

    def test_connector_for_returns_configurable_html(self):
        """connector_for with interamerican-foundation returns ConfigurableHtmlConnector."""
        from app.connectors.factory import connector_for

        connector = connector_for(
            IAF_KEY,
            IAF_URL,
            "html",
            entity_name="Inter-American Foundation",
            default_country="United States",
            connector_config=IAF_CONFIG,
        )
        assert isinstance(connector, ConfigurableHtmlConnector)
        assert connector.source_key == IAF_KEY

    def test_connector_for_no_config_falls_back_to_generic_html(self):
        """Without connector_config, factory falls back to GenericHtmlConnector."""
        from app.connectors.factory import connector_for
        from app.connectors.generic_html import GenericHtmlConnector

        connector = connector_for(
            IAF_KEY,
            IAF_URL,
            "html",
        )
        assert isinstance(connector, GenericHtmlConnector)


# ═══════════════════════════════════════════════════════════════════════
# Fondo Emprender — parse tests (mocked)
# ═══════════════════════════════════════════════════════════════════════


SAMPLE_FONDO_HTML = """<html><body>
<div class="row">
    <h2><a href="https://www.fondoemprender.com/SitePages/Conv123.aspx">Capital Semilla 2026</a></h2>
    <p>Fecha de cierre: 30/09/2026</p>
</div>
<div class="row">
    <h3><a href="https://www.fondoemprender.com/SitePages/Conv456.aspx">Emprendimiento Innovador 2026</a></h3>
    <p>Cierre: 30/10/2026</p>
</div>
<div class="row">
    <a href="https://www.fondoemprender.com/SitePages/ConvExpirada.aspx">Expirada 2025</a>
    <p>Cierre: 15/01/2025</p>
</div>
</body></html>"""

EMPTY_HTML = "<html><body><p>No convocatorias vigentes</p></body></html>"

GARBAGE_HTML = "this is not valid html at all {{{"


class TestFondoEmprenderParse:
    """Parse mocked Fondo Emprender HTML and verify extraction."""

    @pytest.mark.asyncio
    async def test_fetch_and_parse_yields_candidates(self, monkeypatch):
        """Happy path: at least 2 candidates from sample HTML."""
        mock = AsyncMock(return_value=(FONDO_URL, SAMPLE_FONDO_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)

        connector = ConfigurableHtmlConnector(
            FONDO_KEY,
            FONDO_URL,
            FONDO_CONFIG,
            entity_name="Fondo Emprender SENA",
            default_country="Colombia",
        )
        raw = await connector.fetch()
        candidates = await connector.parse(raw)

        assert len(candidates) >= 2
        titles = {c.title for c in candidates}
        assert "Capital Semilla 2026" in titles
        assert "Emprendimiento Innovador 2026" in titles

    @pytest.mark.asyncio
    async def test_fetch_and_parse_skips_closed(self, monkeypatch):
        """Candidates with past close dates are filtered out."""
        mock = AsyncMock(return_value=(FONDO_URL, SAMPLE_FONDO_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)

        connector = ConfigurableHtmlConnector(
            FONDO_KEY,
            FONDO_URL,
            FONDO_CONFIG,
            entity_name="Fondo Emprender SENA",
            default_country="Colombia",
        )
        raw = await connector.fetch()
        candidates = await connector.parse(raw)

        titles = {c.title for c in candidates}
        assert "Expirada 2025" not in titles

    @pytest.mark.asyncio
    async def test_empty_html_returns_empty_list(self, monkeypatch):
        """When the page has no div.row, parse returns []."""
        mock = AsyncMock(return_value=(FONDO_URL, EMPTY_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)

        connector = ConfigurableHtmlConnector(
            FONDO_KEY,
            FONDO_URL,
            FONDO_CONFIG,
            entity_name="Fondo Emprender SENA",
            default_country="Colombia",
        )
        raw = await connector.fetch()
        candidates = await connector.parse(raw)
        assert candidates == []

    @pytest.mark.asyncio
    async def test_garbage_html_does_not_raise(self, monkeypatch):
        """Malformed HTML should not cause parse() to raise."""
        mock = AsyncMock(return_value=(FONDO_URL, GARBAGE_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)

        connector = ConfigurableHtmlConnector(
            FONDO_KEY,
            FONDO_URL,
            FONDO_CONFIG,
            entity_name="Fondo Emprender SENA",
            default_country="Colombia",
        )
        raw = await connector.fetch()
        try:
            candidates = await connector.parse(raw)
            assert isinstance(candidates, list)
        except Exception as exc:
            pytest.fail(f"parse() raised on garbage data: {exc}")

    @pytest.mark.asyncio
    async def test_selectors_diagnostics_tracked(self, monkeypatch):
        """After parse, selector_diagnostics shows which selectors matched."""
        mock = AsyncMock(return_value=(FONDO_URL, SAMPLE_FONDO_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)

        connector = ConfigurableHtmlConnector(
            FONDO_KEY,
            FONDO_URL,
            FONDO_CONFIG,
            entity_name="Fondo Emprender SENA",
            default_country="Colombia",
        )
        raw = await connector.fetch()
        await connector.parse(raw)

        diag = connector.selector_diagnostics
        assert diag["list_selector"] == "div.row"
        assert diag["title_selector"] is not None
        assert diag["link_selector"] is not None


# ═══════════════════════════════════════════════════════════════════════
# Inter-American Foundation — parse tests (mocked)
# ═══════════════════════════════════════════════════════════════════════


SAMPLE_IAF_HTML = """<html><body>
<article>
    <h2><a href="https://iaf.gov/grants/community-dev-2026/">Community Development Grant 2026</a></h2>
    <p>Deadline: 10/01/2027</p>
</article>
<article>
    <h2><a href="https://iaf.gov/grants/youth-leadership-2026/">Youth Leadership Program 2026</a></h2>
    <p>Application Deadline: 12/15/2026</p>
</article>
<article>
    <h2><a href="https://iaf.gov/grants/expired-grant/">Expired Grant 2024</a></h2>
    <p>Due: 01/15/2024</p>
</article>
</body></html>"""


class TestInteramericanParse:
    """Parse mocked IAF HTML and verify extraction."""

    @pytest.mark.asyncio
    async def test_fetch_and_parse_yields_candidates(self, monkeypatch):
        """Happy path: at least 2 candidates from sample HTML."""
        mock = AsyncMock(return_value=(IAF_URL, SAMPLE_IAF_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)

        connector = ConfigurableHtmlConnector(
            IAF_KEY,
            IAF_URL,
            IAF_CONFIG,
            entity_name="Inter-American Foundation",
            default_country="United States",
        )
        raw = await connector.fetch()
        candidates = await connector.parse(raw)

        assert len(candidates) >= 2
        titles = {c.title for c in candidates}
        assert "Community Development Grant 2026" in titles
        assert "Youth Leadership Program 2026" in titles

    @pytest.mark.asyncio
    async def test_fetch_and_parse_skips_closed(self, monkeypatch):
        """Candidates with past close dates are filtered out."""
        mock = AsyncMock(return_value=(IAF_URL, SAMPLE_IAF_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)

        connector = ConfigurableHtmlConnector(
            IAF_KEY,
            IAF_URL,
            IAF_CONFIG,
            entity_name="Inter-American Foundation",
            default_country="United States",
        )
        raw = await connector.fetch()
        candidates = await connector.parse(raw)

        titles = {c.title for c in candidates}
        assert "Expired Grant 2024" not in titles

    @pytest.mark.asyncio
    async def test_empty_html_returns_empty_list(self, monkeypatch):
        """When the page has no article, parse returns []."""
        mock = AsyncMock(return_value=(IAF_URL, EMPTY_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)

        connector = ConfigurableHtmlConnector(
            IAF_KEY,
            IAF_URL,
            IAF_CONFIG,
            entity_name="Inter-American Foundation",
            default_country="United States",
        )
        raw = await connector.fetch()
        candidates = await connector.parse(raw)
        assert candidates == []

    @pytest.mark.asyncio
    async def test_garbage_html_does_not_raise(self, monkeypatch):
        """Malformed HTML should not cause parse() to raise."""
        mock = AsyncMock(return_value=(IAF_URL, GARBAGE_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)

        connector = ConfigurableHtmlConnector(
            IAF_KEY,
            IAF_URL,
            IAF_CONFIG,
            entity_name="Inter-American Foundation",
            default_country="United States",
        )
        raw = await connector.fetch()
        try:
            candidates = await connector.parse(raw)
            assert isinstance(candidates, list)
        except Exception as exc:
            pytest.fail(f"parse() raised on garbage data: {exc}")

    @pytest.mark.asyncio
    async def test_selectors_diagnostics_tracked(self, monkeypatch):
        """After parse, selector_diagnostics shows which selectors matched."""
        mock = AsyncMock(return_value=(IAF_URL, SAMPLE_IAF_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)

        connector = ConfigurableHtmlConnector(
            IAF_KEY,
            IAF_URL,
            IAF_CONFIG,
            entity_name="Inter-American Foundation",
            default_country="United States",
        )
        raw = await connector.fetch()
        await connector.parse(raw)

        diag = connector.selector_diagnostics
        assert diag["list_selector"] == "article"
        assert diag["title_selector"] is not None
        assert diag["link_selector"] is not None
