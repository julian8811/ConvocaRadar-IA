"""Tests for FONDECYT Chile connector — ConfigurableHtmlConnector.

FONDECYT's page at anid.cl/concursos/ is a WordPress + Elementor + JetEngine
site. The actual contest listings are in .jet-listing-grid__item containers.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.connectors.configurable_html import ConfigurableHtmlConnector

FONDECYT_KEY = "fondecyt-chile"
FONDECYT_URL = "https://www.anid.cl/concursos/"

FONDECYT_CONFIG: dict = {
    "list_selectors": [".jet-listing-grid__item"],
    "title_selectors": ["h3"],
    "link_selectors": ["a[href*='concursos/']"],
    "content_selectors": [".jet-listing-grid__item"],
    "date_labels": ["Inicio:", "Cierre:", "Fecha estimada de fallo:"],
    "detail_enrichment": False,
}

SAMPLE_HTML = """<html><body>
<div data-elementor-type="archive">
<div class="jet-listing-grid__item jet-listing-dynamic-post-31077">
    <div class="jet-engine-listing-overlay-wrap">
        <a href="https://anid.cl/concursos/concurso-fondo-quimal-2026/" class="jet-engine-listing-overlay-link"></a>
    </div>
    <h3 class="elementor-heading-title">Concurso Fondo QUIMAL 2027</h3>
    <div class="jet-listing-dynamic-field__content">Inicio: 3 de julio, 2027</div>
    <div class="jet-listing-dynamic-field__content">Cierre: 14 de agosto, 2027 - 13:00</div>
    <div class="jet-listing-dynamic-field__content">Fecha estimada de fallo: noviembre 2027</div>
    <a class="jet-listing-dynamic-link__link" href="https://anid.cl/concursos/concurso-fondo-quimal-2026/"><span>Ver más</span></a>
</div>
<div class="jet-listing-grid__item jet-listing-dynamic-post-31078">
    <div class="jet-engine-listing-overlay-wrap">
        <a href="https://anid.cl/concursos/concurso-asignacion-de-tiempo-de-buque-oceanografico-2/" class="jet-engine-listing-overlay-link"></a>
    </div>
    <h3 class="elementor-heading-title">Concurso Asignación de Tiempo de Buque Oceanográfico 2027</h3>
    <div class="jet-listing-dynamic-field__content">Inicio: 25 de junio, 2027</div>
    <div class="jet-listing-dynamic-field__content">Cierre: 29 de julio, 2027 - 13:00</div>
    <a class="jet-listing-dynamic-link__link" href="https://anid.cl/concursos/concurso-asignacion-de-tiempo-de-buque-oceanografico-2/"><span>Ver más</span></a>
</div>
<div class="jet-listing-grid__item jet-listing-dynamic-post-31079">
    <h3 class="elementor-heading-title">Closed Call Already Expired</h3>
    <div class="jet-listing-dynamic-field__content">Inicio: 10 enero, 2025</div>
    <div class="jet-listing-dynamic-field__content">Cierre: 28 febrero, 2025</div>
    <a class="jet-listing-dynamic-link__link" href="https://anid.cl/concursos/closed-call-expired/"><span>Ver más</span></a>
</div>
</div>
</body></html>"""

EMPTY_HTML = "<html><body><p>No contests found</p></body></html>"
GARBAGE_HTML = "this is not valid html at all {{{"


class TestFondecytConnectorConfig:
    def test_config_is_valid(self):
        from app.connectors.configurable_html import HtmlConnectorConfig

        config = HtmlConnectorConfig.from_dict(FONDECYT_CONFIG)
        assert config.list_selectors == [".jet-listing-grid__item"]
        assert config.title_selectors == ["h3"]
        assert config.link_selectors == ["a[href*='concursos/']"]
        assert "Cierre:" in config.date_labels

    def test_connector_for_returns_configurable_html(self):
        from app.connectors.factory import connector_for

        connector = connector_for(
            FONDECYT_KEY,
            FONDECYT_URL,
            "html",
            entity_name="FONDECYT",
            default_country="Chile",
            connector_config=FONDECYT_CONFIG,
        )
        assert isinstance(connector, ConfigurableHtmlConnector)
        assert connector.source_key == FONDECYT_KEY


class TestFondecytParse:
    @pytest.mark.asyncio
    async def test_fetch_and_parse_yields_candidates(self, monkeypatch):
        mock = AsyncMock(return_value=(FONDECYT_URL, SAMPLE_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)
        connector = ConfigurableHtmlConnector(
            FONDECYT_KEY, FONDECYT_URL, FONDECYT_CONFIG,
            entity_name="FONDECYT", default_country="Chile",
        )
        candidates = await connector.parse(await connector.fetch())
        titles = {c.title for c in candidates}
        assert "Concurso Fondo QUIMAL 2027" in titles
        assert "Concurso Asignación de Tiempo de Buque Oceanográfico 2027" in titles

    @pytest.mark.asyncio
    async def test_fetch_and_parse_emits_closed_for_status_reconciliation(self, monkeypatch):
        """Past calls survive parse; validate/reconcile owns closed status."""
        mock = AsyncMock(return_value=(FONDECYT_URL, SAMPLE_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)
        connector = ConfigurableHtmlConnector(
            FONDECYT_KEY, FONDECYT_URL, FONDECYT_CONFIG,
            entity_name="FONDECYT", default_country="Chile",
        )
        candidates = await connector.parse(await connector.fetch())
        closed = next(c for c in candidates if c.title == "Closed Call Already Expired")
        assert closed.close_date is not None
        validation = await connector.validate(closed)
        assert validation.ok is False

    @pytest.mark.asyncio
    async def test_empty_html_returns_empty_list(self, monkeypatch):
        mock = AsyncMock(return_value=(FONDECYT_URL, EMPTY_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)
        connector = ConfigurableHtmlConnector(
            FONDECYT_KEY, FONDECYT_URL, FONDECYT_CONFIG,
            entity_name="FONDECYT", default_country="Chile",
        )
        assert await connector.parse(await connector.fetch()) == []

    @pytest.mark.asyncio
    async def test_garbage_html_does_not_raise(self, monkeypatch):
        mock = AsyncMock(return_value=(FONDECYT_URL, GARBAGE_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)
        connector = ConfigurableHtmlConnector(
            FONDECYT_KEY, FONDECYT_URL, FONDECYT_CONFIG,
            entity_name="FONDECYT", default_country="Chile",
        )
        candidates = await connector.parse(await connector.fetch())
        assert isinstance(candidates, list)

    @pytest.mark.asyncio
    async def test_selectors_diagnostics_tracked(self, monkeypatch):
        mock = AsyncMock(return_value=(FONDECYT_URL, SAMPLE_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)
        connector = ConfigurableHtmlConnector(
            FONDECYT_KEY, FONDECYT_URL, FONDECYT_CONFIG,
            entity_name="FONDECYT", default_country="Chile",
        )
        await connector.parse(await connector.fetch())
        diag = connector.selector_diagnostics
        assert diag["list_selector"] == ".jet-listing-grid__item"
        assert diag["title_selector"] == "h3"
        assert diag["link_selector"] is not None
