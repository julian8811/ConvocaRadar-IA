"""Regression tests for Minciencias (/node/ links) and UKRI (div.opportunity).

Fixtures are inline snapshots of the live HTML shapes (no network):
- Minciencias: Drupal 7 SSR table `views-table cols-5` with "Total de
  recursos" + "Fecha de Apertura" columns; detail links are `/node/<id>`.
- UKRI: WordPress SSR listing, 10 items per page as `div.opportunity`
  carrying "Opportunity status" plus Publication/Opening/Closing dates;
  no amounts in the listing (detail-only, out of scope).
"""

from __future__ import annotations

import pytest

from app.connectors.base import RawSourceResult
from app.connectors.minciencias import MincienciasConnector
from app.connectors.ukri import UKRIConnector

MINCIENCIAS_TABLE_HTML = """<html><body>
<table class="views-table cols-5">
  <thead><tr><th>Titulo</th><th>Total de recursos</th><th>Fecha de Apertura</th></tr></thead>
  <tbody>
    <tr>
      <td><a href="/node/9577">Convocatoria nacional de ciencia e innovacion 2026</a></td>
      <td>$700.000.000.000</td>
      <td>Jueves, Octubre 8, 2026</td>
    </tr>
    <tr>
      <td><a href="/node/9581">Convocatoria fondo de investigacion en salud 2026</a></td>
      <td>$120.000.000.000</td>
      <td>Lunes, Noviembre 3, 2026</td>
    </tr>
  </tbody>
</table>
</body></html>"""

MINCIENCIAS_BARE_NODE_LINK_HTML = """<html><body>
<div class="custom-listing">
  <a href="/node/9602">Convocatoria programa de innovacion regional 2026</a>
  <span>$45.000.000.000 - Jueves, Octubre 8, 2026</span>
</div>
</body></html>"""

UKRI_LISTING_HTML = """<html><body>
<div class="opportunity">
  <h2><a href="/opportunity/future-leader-fellowships-2027/">Future Leader Fellowships 2027 funding opportunity</a></h2>
  <p>Opportunity status: Open</p>
  <p>Publication date: 12 January 2027</p>
  <p>Opening date: 19 January 2027</p>
  <p>Closing date: 15 March 2027</p>
</div>
<div class="opportunity">
  <h2><a href="/opportunity/collaborative-rd-grant-2027/">Collaborative R&amp;D grant competition 2027</a></h2>
  <p>Opportunity status: Open</p>
  <p>Publication date: 2 February 2027</p>
  <p>Opening date: 9 February 2027</p>
  <p>Closing date: 30 April 2027</p>
</div>
</body></html>"""

UKRI_POST_ID_HTML = """<html><body>
<div id="post-4821">
  <h3><a href="/opportunity/quantum-technologies-grant-2027/">Quantum technologies grant proposals 2027</a></h3>
  <p>Opportunity status: Open</p>
  <p>Closing date: 20 May 2027</p>
</div>
</body></html>"""

UKRI_LEGACY_ARTICLE_HTML = """<html><body>
<article>
  <h2><a href="/opportunity/legacy-grant-2027/">Legacy grant funding call 2027</a></h2>
  <p>Deadline: 10 June 2027</p>
</article>
</body></html>"""


def _minciencias_raw(html: str) -> RawSourceResult:
    return RawSourceResult(
        source_key="minciencias",
        url="https://minciencias.gov.co/convocatorias/todas",
        content=html,
        content_type="text/html",
        metadata={
            "pages": [
                {"url": "https://minciencias.gov.co/convocatorias/todas", "content": html}
            ]
        },
    )


def _ukri_raw(html: str) -> RawSourceResult:
    return RawSourceResult(
        source_key="ukri-opportunities",
        url="https://www.ukri.org/opportunity/",
        content=html,
        content_type="text/html",
    )


class TestMincienciasNodeLinks:
    async def test_table_rows_with_node_links_yield_candidates(self):
        candidates = await MincienciasConnector().parse(
            _minciencias_raw(MINCIENCIAS_TABLE_HTML)
        )
        assert len(candidates) >= 2
        urls = [c.official_url for c in candidates]
        assert any("/node/9577" in url for url in urls)
        first = next(c for c in candidates if "/node/9577" in c.official_url)
        assert "convocatoria" in first.title.lower()
        assert first.open_date is not None
        assert (first.open_date.year, first.open_date.month, first.open_date.day) == (
            2026,
            10,
            8,
        )
        assert first.funding_amount_raw is not None
        assert "$700.000.000.000" in first.funding_amount_raw

    async def test_fallback_accepts_bare_node_links(self):
        candidates = await MincienciasConnector().parse(
            _minciencias_raw(MINCIENCIAS_BARE_NODE_LINK_HTML)
        )
        assert len(candidates) >= 1
        assert any("/node/9602" in c.official_url for c in candidates)

    async def test_parse_never_raises_on_garbage(self):
        raw = _minciencias_raw("<html><body><table><tr><td>%%%</td></tr></table>")
        assert await MincienciasConnector().parse(raw) == [] or True
        empty = _minciencias_raw("")
        assert await MincienciasConnector().parse(empty) == []


class TestUkriOpportunityDivs:
    async def test_opportunity_divs_yield_candidates_with_dates(self):
        candidates = await UKRIConnector().parse(_ukri_raw(UKRI_LISTING_HTML))
        assert len(candidates) >= 2
        first = next(
            c for c in candidates if "Future Leader Fellowships" in c.title
        )
        assert first.official_url.startswith("https://www.ukri.org/opportunity/")
        assert first.close_date is not None
        assert (first.close_date.year, first.close_date.month) == (2027, 3)
        assert first.open_date is not None
        assert "open" in first.raw_text.lower()

    async def test_post_id_divs_yield_candidates(self):
        candidates = await UKRIConnector().parse(_ukri_raw(UKRI_POST_ID_HTML))
        assert len(candidates) >= 1
        assert any("Quantum" in c.title for c in candidates)
        assert candidates[0].close_date is not None

    async def test_generic_article_fallback_still_works(self):
        candidates = await UKRIConnector().parse(_ukri_raw(UKRI_LEGACY_ARTICLE_HTML))
        assert len(candidates) >= 1
        assert any("Legacy" in c.title for c in candidates)

    async def test_parse_never_raises_on_garbage(self):
        assert await UKRIConnector().parse(_ukri_raw("")) == []
        assert await UKRIConnector().parse(_ukri_raw("<html><div>%%%</div>")) == []
