"""Connectors must persist every field extractable from list cards and detail pages.

The shared extractors already know how to read dates, funding, narrative
sections and apply URLs. These tests pin that ConfigurableHtml and GenericHtml
actually copy those values onto OpportunityCandidate instead of dropping them
at merge time.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.connectors.configurable_html import ConfigurableHtmlConnector
from app.connectors.generic_html import GenericHtmlConnector
from app.connectors.rss import RssConnector
from app.connectors.api import ApiConnector
from app.connectors.base import RawSourceResult

LIST_HTML = """<html><body>
<div class="card">
  <h2><a href="/grant/1">Convocatoria de Innovación 2026</a></h2>
  <p>Apertura: 15 de marzo de 2026. Cierre: 30 de septiembre de 2026.</p>
  <p>Monto: hasta 500 millones de pesos colombianos.</p>
</div>
</body></html>"""

DETAIL_HTML = """<html><body>
<article>
<h1>Convocatoria de Innovación 2026 — ficha</h1>
<p>El Ministerio abre la convocatoria para cofinanciar proyectos de innovación empresarial con enfoque regional.</p>
<p>Apertura: 15 de marzo de 2026. Fecha de cierre: 30 de septiembre de 2026.</p>
<p>Monto: hasta 500 millones de pesos colombianos.</p>
<p>¿Quién puede participar?</p>
<ul><li>Empresas colombianas legalmente constituidas</li></ul>
<p>Requisitos:</p>
<ul><li>Estar registrado en el sistema nacional</li></ul>
<p>Documentos requeridos:</p>
<ul><li>Certificado de existencia y representación legal</li></ul>
<p>Criterios de evaluación:</p>
<ul><li>Pertinencia técnica de la propuesta</li></ul>
<p>Restricciones:</p>
<ul><li>No podrán participar entidades sancionadas fiscalmente</li></ul>
<p><a href="/postular">Postular ahora</a></p>
</article>
</body></html>"""

CONFIG = {
    "list_selectors": [".card"],
    "title_selectors": ["h2 a"],
    "link_selectors": ["a[href]"],
    "content_selectors": ["article", ".card"],
    "date_labels": ["Apertura:", "Cierre:"],
    "detail_enrichment": True,
}

FONDECYT_CARD = """<html><body>
<div class="jet-listing-grid__item">
    <h3>Concurso Fondo QUIMAL 2027</h3>
    <div>Inicio: 3 de julio, 2027</div>
    <div>Cierre: 14 de agosto, 2027 - 13:00</div>
    <a href="https://anid.cl/concursos/concurso-fondo-quimal-2026/">Ver más</a>
</div>
</body></html>"""

FONDECYT_CONFIG = {
    "list_selectors": [".jet-listing-grid__item"],
    "title_selectors": ["h3"],
    "link_selectors": ["a[href*='concursos/']"],
    "content_selectors": [".jet-listing-grid__item"],
    "date_labels": ["Inicio:", "Cierre:"],
    "detail_enrichment": False,
}


@pytest.fixture
def fetch_list_and_detail(monkeypatch):
    async def _mock(url: str, **kwargs):
        if "/grant/" in url or "/postular" in url:
            return (url, DETAIL_HTML, "text/html")
        return (url, LIST_HTML, "text/html")

    mock = AsyncMock(side_effect=_mock)
    monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)
    monkeypatch.setattr("app.connectors.generic_html.fetch_httpx_text", mock)
    monkeypatch.setattr("app.connectors.configurable_html.common.fetch_httpx_text", mock)
    return mock


class TestConfigurableHtmlFullCapture:
    @pytest.mark.asyncio
    async def test_list_card_captures_dates_and_funding(self, monkeypatch):
        mock = AsyncMock(return_value=("http://example.com", LIST_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)
        config = {**CONFIG, "detail_enrichment": False}
        connector = ConfigurableHtmlConnector("k", "http://example.com", config)
        candidates = await connector.parse(await connector.fetch())
        assert len(candidates) == 1
        item = candidates[0]
        assert item.close_date is not None and item.close_date.month == 9
        assert item.open_date is not None and item.open_date.month == 3
        assert item.funding_amount_raw
        assert item.funding_amount_value == 500_000_000
        assert item.funding_amount_currency == "COP"

    @pytest.mark.asyncio
    async def test_detail_enrichment_captures_narrative_and_apply_url(self, fetch_list_and_detail):
        connector = ConfigurableHtmlConnector("k", "http://example.com", CONFIG)
        candidates = await connector.parse(await connector.fetch())
        assert len(candidates) == 1
        item = candidates[0]
        assert item.eligible_applicants
        assert item.requirements
        assert item.documents_required
        assert item.evaluation_criteria
        assert item.restrictions
        assert item.application_url and item.application_url.endswith("/postular")
        assert item.raw_text and "pertinencia" in item.raw_text.lower()

    @pytest.mark.asyncio
    async def test_fondecyt_card_captures_inicio_and_cierre(self, monkeypatch):
        mock = AsyncMock(return_value=("https://anid.cl/concursos/", FONDECYT_CARD, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)
        connector = ConfigurableHtmlConnector(
            "fondecyt-chile",
            "https://anid.cl/concursos/",
            FONDECYT_CONFIG,
            entity_name="FONDECYT",
            default_country="Chile",
        )
        candidates = await connector.parse(await connector.fetch())
        assert len(candidates) == 1
        item = candidates[0]
        assert item.open_date is not None
        assert item.open_date.month == 7 and item.open_date.day == 3
        assert item.close_date is not None
        assert item.close_date.month == 8 and item.close_date.day == 14
        assert item.open_date.year == 2027


class TestGenericHtmlFullCapture:
    @pytest.mark.asyncio
    async def test_detail_merge_keeps_narrative_fields(self, fetch_list_and_detail):
        connector = GenericHtmlConnector("k", "http://example.com", entity_name="Minciencias")
        candidates = await connector.parse(await connector.fetch())
        assert candidates
        item = candidates[0]
        assert item.close_date is not None
        assert item.funding_amount_raw
        assert item.eligible_applicants or item.requirements
        assert item.application_url


class TestRssAndApiFieldMapping:
    @pytest.mark.asyncio
    async def test_rss_extracts_deadline_and_funding_from_description(self):
        xml = """<?xml version="1.0"?>
        <rss><channel>
        <item>
          <title>Beca de investigación 2026</title>
          <link>https://fondo.org/beca</link>
          <description>Deadline: 30 September 2026. Funding: USD 25,000. Who can apply: doctoral researchers.</description>
        </item>
        </channel></rss>"""
        connector = RssConnector("rss-test", "https://fondo.org/feed.xml", entity="Fondo")
        candidates = await connector.parse(
            RawSourceResult("rss-test", "https://fondo.org/feed.xml", xml, "application/rss+xml")
        )
        assert len(candidates) == 1
        item = candidates[0]
        assert item.close_date is not None and item.close_date.month == 9
        assert item.funding_amount_raw
        assert item.funding_amount_value == 25_000
        assert item.funding_amount_currency == "USD"

    @pytest.mark.asyncio
    async def test_api_maps_dates_funding_and_application_url(self):
        payload = """{
          "items": [{
            "title": "Innovation Call 2026",
            "url": "https://api.example.org/calls/1",
            "description": "Support for regional innovation projects.",
            "openDate": "2026-03-15",
            "deadline": "2026-09-30",
            "fundingAmount": "EUR 100000",
            "applicationUrl": "https://api.example.org/apply/1",
            "id": "CALL-1"
          }]
        }"""
        connector = ApiConnector("api-test", "https://api.example.org/calls")
        candidates = await connector.parse(
            RawSourceResult("api-test", "https://api.example.org/calls", payload, "application/json")
        )
        assert len(candidates) == 1
        item = candidates[0]
        assert item.open_date is not None and item.open_date.month == 3
        assert item.close_date is not None and item.close_date.month == 9
        assert item.funding_amount_raw
        assert item.application_url == "https://api.example.org/apply/1"
        assert item.external_id == "CALL-1"
        assert item.description
