"""Closed candidates must be emitted at parse — not silently dropped.

Status ownership stays with runner soft-pass + reconcile_deadline_status.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from selectolax.parser import HTMLParser

from app.connectors.apc_colombia import ApcColombiaConnector
from app.connectors.base import RawSourceResult
from app.connectors.configurable_html import ConfigurableHtmlConnector
from app.connectors.generic_html import GenericHtmlConnector
from app.connectors.innpulsa import InnpulsaConnector
from app.connectors.minciencias import MincienciasConnector
from app.connectors.unwomen_innovate import UnwomenInnovateConnector
from app.connectors.world_bank import WorldBankConnector


@pytest.fixture
def no_deep_fetch(monkeypatch):
    """Avoid network during generic_html parse enrichment."""

    async def _identity(self, candidates):
        return candidates

    monkeypatch.setattr(GenericHtmlConnector, "_deep_fetch_candidates", _identity)


@pytest.mark.asyncio
async def test_generic_html_emits_closed_list_card(no_deep_fetch):
    html = """
    <html><body>
      <article>
        <a href="/convocatorias/cerrada-2024">Convocatoria de innovación cerrada</a>
        <p>Estado: Cerrada. Ya no acepta postulaciones.</p>
      </article>
    </body></html>
    """
    raw = RawSourceResult(
        source_key="generic-closed",
        url="https://example.gov.co/list",
        content=html,
        content_type="text/html",
    )
    candidates = await GenericHtmlConnector("generic-closed", raw.url).parse(raw)
    assert len(candidates) >= 1
    closed = next(c for c in candidates if "cerrada" in c.title.lower() or "cerrada" in (c.summary or "").lower())
    assert closed.official_url.endswith("/convocatorias/cerrada-2024")
    assert "cerrad" in f"{closed.title} {closed.summary} {closed.raw_text}".lower()


@pytest.mark.asyncio
async def test_generic_html_emits_past_close_date_json(no_deep_fetch):
    past = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d")
    payload = {
        "items": [
            {
                "title": "Convocatoria con deadline pasado",
                "url": "https://example.gov.co/past-deadline",
                "summary": "Convocatoria de investigación abierta formalmente",
                "close_date": past,
            }
        ]
    }
    raw = RawSourceResult(
        source_key="generic-past",
        url="https://example.gov.co/api",
        content=json.dumps(payload),
        content_type="application/json",
    )
    candidates = await GenericHtmlConnector("generic-past", raw.url).parse(raw)
    assert len(candidates) == 1
    assert candidates[0].close_date is not None
    assert candidates[0].close_date.date() < datetime.now(UTC).date()


@pytest.mark.asyncio
async def test_configurable_html_emits_closed_card():
    html = """
    <html><body>
      <div class="card">
        <h2><a href="/grant/closed">Grant Closed Innovation Call</a></h2>
        <p class="deadline">Estado: Cerrada. Cierre: 15/01/2024</p>
      </div>
    </body></html>
    """
    config = {
        "list_selectors": [".card"],
        "title_selectors": ["h2 a"],
        "link_selectors": ["a[href]"],
        "content_selectors": [".deadline"],
        "date_labels": ["Cierre:", "Deadline:"],
    }
    connector = ConfigurableHtmlConnector(
        "cfg-closed", "https://example.gov.co", config, entity_name="Test Entity"
    )
    raw = RawSourceResult(
        source_key="cfg-closed",
        url="https://example.gov.co/list",
        content=html,
        content_type="text/html",
    )
    candidates = await connector.parse(raw)
    assert len(candidates) == 1
    assert "closed" in candidates[0].title.lower() or "cerrad" in candidates[0].raw_text.lower()
    assert candidates[0].close_date is not None or "cerrad" in (
        f"{candidates[0].title} {candidates[0].summary} {candidates[0].raw_text}".lower()
    )


@pytest.mark.asyncio
async def test_apc_colombia_emits_closed_title():
    html = """
    <html><body>
      <article class="page teaser">
        <a href="https://www.apccolombia.gov.co/convocatoria-cerrada-cooperacion">
          Convocatoria cerrada de cooperacion triangular 2024
        </a>
        <p>Estado: Cerrada</p>
      </article>
    </body></html>
    """
    raw = RawSourceResult(
        source_key="apc-colombia",
        url="https://www.apccolombia.gov.co/list",
        content=html,
        content_type="text/html",
        metadata={"pages": [{"url": "https://www.apccolombia.gov.co/list", "content": html}]},
    )
    candidates = await ApcColombiaConnector().parse(raw)
    assert len(candidates) >= 1
    assert any("cerrada" in c.title.lower() for c in candidates)


@pytest.mark.asyncio
async def test_minciencias_emits_closed_title():
    html = """
    <html><body>
      <div class="views-row">
        <a href="/convocatorias/cerrada-ciencia-2023">
          Convocatoria cerrada de ciencia e innovacion
        </a>
        <p>Estado: Finalizada</p>
      </div>
    </body></html>
    """
    raw = RawSourceResult(
        source_key="minciencias",
        url="https://minciencias.gov.co/convocatorias/todas",
        content=html,
        content_type="text/html",
        metadata={
            "pages": [
                {
                    "url": "https://minciencias.gov.co/convocatorias/todas",
                    "content": html,
                }
            ]
        },
    )
    candidates = await MincienciasConnector().parse(raw)
    assert len(candidates) >= 1
    assert any("cerrada" in c.title.lower() for c in candidates)


@pytest.mark.asyncio
async def test_unwomen_emits_closed_past_deadline():
    past = (datetime.now(UTC) - timedelta(days=14)).strftime("%Y-%m-%d")
    html = f"""
    <html><body>
      <article>
        <a href="https://www.unwomen.org/en/news/stories/closed-women-innovation-grant">
          Closed women innovation technology grant call
        </a>
        <p>Deadline: {past}. Applications closed.</p>
      </article>
    </body></html>
    """
    raw = RawSourceResult(
        source_key="unwomen-innovate",
        url="https://www.unwomen.org/en/news",
        content=html,
        content_type="text/html",
    )
    candidates = await UnwomenInnovateConnector().parse(raw)
    assert len(candidates) >= 1
    closed = candidates[0]
    assert closed.close_date is not None or "closed" in (
        f"{closed.title} {closed.summary} {closed.raw_text}".lower()
    )


@pytest.mark.asyncio
async def test_innpulsa_api_emits_closed_status():
    past = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%d")
    payload = [
        {
            "id": "99",
            "slug": "convocatoria-cerrada",
            "title": "Convocatoria Innovacion Cerrada",
            "description": "Programa de emprendimiento finalizado",
            "status": "cerrada",
            "category": "innovacion",
            "start_date": "2024-01-01",
            "end_date": past,
        }
    ]
    raw = RawSourceResult(
        source_key="innpulsa",
        url="https://api.innpulsacolombia.com/items",
        content=json.dumps(payload),
        content_type="application/json",
        metadata={"fetch_mode": "api"},
    )
    candidates = await InnpulsaConnector().parse(raw)
    assert len(candidates) == 1
    assert candidates[0].close_date is not None
    assert candidates[0].official_url


@pytest.mark.asyncio
async def test_innpulsa_html_container_emits_closed_text():
    html = """
    <html><body>
      <article>
        <a href="https://www.innpulsacolombia.com/convocatoria-cerrada">
          Convocatoria Emprendimiento Digital Cerrada
        </a>
        <p>Estado: Cerrada. Fecha 01/01/2024</p>
      </article>
    </body></html>
    """
    raw = RawSourceResult(
        source_key="innpulsa",
        url="https://www.innpulsacolombia.com/",
        content=html,
        content_type="text/html",
        metadata={"fetch_mode": "html"},
    )
    # Force HTML container path (no browser cards)
    candidates = await InnpulsaConnector().parse(raw)
    assert len(candidates) >= 1
    assert any(
        "cerrad" in f"{c.title} {c.summary} {c.raw_text}".lower() for c in candidates
    )


@pytest.mark.asyncio
async def test_world_bank_emits_past_close_date():
    past = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    future = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    payload = {
        "procnotices": {
            "WB-OPEN": {
                "id": "WB-OPEN",
                "bid_description": "Open School Construction",
                "submission_date": f"{future}T23:59:59",
                "project_name": "Education",
                "project_ctry_name": "Colombia",
            },
            "WB-PAST": {
                "id": "WB-PAST",
                "bid_description": "Expired Road Construction",
                "submission_date": f"{past}T23:59:59",
                "project_name": "Highway Project",
                "project_ctry_name": "Brazil",
            },
        }
    }
    raw = RawSourceResult(
        source_key="world-bank-procurement",
        url="https://search.worldbank.org/api/v2/procnotices",
        content=json.dumps(payload),
        content_type="application/json",
    )
    candidates = await WorldBankConnector().parse(raw)
    titles = [c.title for c in candidates]
    assert "Expired Road Construction" in titles
    past_c = next(c for c in candidates if c.title == "Expired Road Construction")
    assert past_c.close_date is not None
    assert past_c.close_date < datetime.now()


def test_innpulsa_container_helper_emits_closed():
    """Unit triangulation: container builder must not return None for closed text."""
    html = """
    <article>
      <a href="https://www.innpulsacolombia.com/foo">
        Convocatoria Emprendimiento Digital
      </a>
      Estado: Cerrada. Postulaciones finalizadas.
    </article>
    """
    tree = HTMLParser(html)
    container = tree.css_first("article")
    candidate = InnpulsaConnector()._candidate_from_container(
        container, "https://www.innpulsacolombia.com/"
    )
    assert candidate is not None
    assert "cerrad" in candidate.raw_text.lower()
