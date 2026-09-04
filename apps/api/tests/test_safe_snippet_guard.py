"""Guarded candidate-scoped snippet HTML — never blind list-page fill.

Spec domain: guarded-candidate-fill.
Design: is_safe_candidate_snippet + OpportunityCandidate.snippet_html + runner guard.
"""

from __future__ import annotations

import pytest

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.common import is_safe_candidate_snippet
from app.connectors.configurable_html import ConfigurableHtmlConnector, HtmlConnectorConfig
from app.connectors.generic_html import GenericHtmlConnector
from app.scraper.runner import _scrape_candidates

CARD_URL = "https://example.gov.co/convocatorias/beca-2026"
CARD_HTML = (
    '<article class="card">'
    f'<a href="{CARD_URL}">Beca de investigación 2026</a>'
    "<p>Fecha límite: 30 de septiembre 2026. Elegibles: universidades.</p>"
    "</article>"
)

LIST_PAGE_HTML = f"""<!DOCTYPE html>
<html>
<body>
  <div class="listing">
    {CARD_HTML}
    <article class="card">
      <a href="https://example.gov.co/convocatorias/otra">Otra convocatoria</a>
      <p>Segunda tarjeta de la lista.</p>
    </article>
  </div>
</body>
</html>
"""

RSS_DESC_HTML = (
    "<p>Convocatoria abierta para proyectos de innovación.</p>"
    "<ul><li>Universidades</li><li>Centros de I+D</li></ul>"
)

WB_NOTICE_HTML = (
    "<div class='notice'>"
    "<p>Procurement notice for consulting services.</p>"
    "<p>Submission deadline applies to this notice only.</p>"
    "</div>"
)


def _candidate(**overrides) -> OpportunityCandidate:
    base = dict(
        title="Beca de investigación 2026",
        entity="Example",
        country="Colombia",
        official_url=CARD_URL,
        summary="Beca de investigación",
        raw_text="Beca de investigación 2026. Fecha límite: 30 de septiembre 2026.",
    )
    base.update(overrides)
    return OpportunityCandidate(**base)


# ── Guard unit tests ─────────────────────────────────────────────────────────


def test_rejects_full_html_document():
    assert is_safe_candidate_snippet(LIST_PAGE_HTML, CARD_URL) is False
    assert is_safe_candidate_snippet("<html><body><p>x</p></body></html>", CARD_URL) is False
    assert is_safe_candidate_snippet("<!DOCTYPE html><p>fragment</p>", None) is False
    assert is_safe_candidate_snippet("<body><p>only body</p></body>", CARD_URL) is False


def test_rejects_multi_card_shell():
    multi = (
        '<div class="views-row"><a href="https://a.example/1">One convocatoria</a></div>'
        '<div class="views-row"><a href="https://a.example/2">Two convocatoria</a></div>'
    )
    assert is_safe_candidate_snippet(multi, "https://a.example/1") is False


def test_rejects_empty_and_oversized():
    assert is_safe_candidate_snippet("", CARD_URL) is False
    assert is_safe_candidate_snippet(None, CARD_URL) is False  # type: ignore[arg-type]
    assert is_safe_candidate_snippet("x" * 50_001, CARD_URL) is False


def test_accepts_single_card_fragment():
    assert is_safe_candidate_snippet(CARD_HTML, CARD_URL) is True


def test_accepts_rss_description_html():
    assert is_safe_candidate_snippet(RSS_DESC_HTML, CARD_URL) is True


def test_accepts_world_bank_notice_text_html():
    assert (
        is_safe_candidate_snippet(
            WB_NOTICE_HTML,
            "https://projects.worldbank.org/en/projects-operations/procurement-detail/OP001",
        )
        is True
    )


# ── Candidate field ──────────────────────────────────────────────────────────


def test_opportunity_candidate_carries_snippet_html():
    c = _candidate(snippet_html=CARD_HTML)
    assert c.snippet_html == CARD_HTML


# ── Runner guarded fill ──────────────────────────────────────────────────────


class _SnippetConnector:
    source_key = "snippet-source"

    def __init__(self, candidates: list[OpportunityCandidate], list_html: str) -> None:
        self._candidates = candidates
        self._list_html = list_html

    async def fetch(self) -> RawSourceResult:
        return RawSourceResult(
            source_key=self.source_key,
            url="https://example.gov.co/list",
            content=self._list_html,
            content_type="text/html",
        )

    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]:
        return list(self._candidates)

    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult:
        return ValidationResult(ok=True)


class _Src:
    id = "src-snippet"
    key = "snippet-source"
    name = "Snippet Source"
    base_url = "https://example.gov.co"
    source_type = "html"
    country = "Colombia"
    category: list[str] = []
    region = None
    connector_config = None


@pytest.mark.asyncio
async def test_runner_passes_safe_snippet_html_not_list_page(monkeypatch):
    """Runner MAY pass candidate snippet_html when safe; MUST NOT use raw.content."""
    captured: list[dict] = []
    safe_candidate = _candidate(snippet_html=CARD_HTML)

    def _capture(candidate, *, html=None, text=None, page_url=None):
        captured.append({"html": html, "text": text, "page_url": page_url})
        return candidate

    monkeypatch.setattr(
        "app.connectors.factory.connector_for",
        lambda *a, **k: _SnippetConnector([safe_candidate], LIST_PAGE_HTML),
    )
    # Local import inside _scrape_candidates resolves at call time.
    monkeypatch.setattr("app.connectors.common.fill_candidate_from_content", _capture)

    items = await _scrape_candidates(_Src())
    assert len(items) == 1
    assert len(captured) == 1
    assert captured[0]["html"] == CARD_HTML
    assert captured[0]["html"] != LIST_PAGE_HTML
    assert "<html" not in (captured[0]["html"] or "").lower()


@pytest.mark.asyncio
async def test_runner_never_blind_raw_content(monkeypatch):
    """Without a safe candidate snippet, html= must be None — not list raw.content."""
    captured: list[dict] = []
    thin = _candidate(snippet_html=None)

    def _capture(candidate, *, html=None, text=None, page_url=None):
        captured.append({"html": html, "text": text})
        return candidate

    monkeypatch.setattr(
        "app.connectors.factory.connector_for",
        lambda *a, **k: _SnippetConnector([thin], LIST_PAGE_HTML),
    )
    monkeypatch.setattr("app.connectors.common.fill_candidate_from_content", _capture)

    items = await _scrape_candidates(_Src())
    assert len(items) == 1
    assert len(captured) == 1
    assert captured[0]["html"] is None
    assert captured[0]["text"]


@pytest.mark.asyncio
async def test_runner_rejects_unsafe_snippet_html(monkeypatch):
    captured: list[dict] = []
    unsafe = _candidate(snippet_html=LIST_PAGE_HTML)

    def _capture(candidate, *, html=None, text=None, page_url=None):
        captured.append({"html": html})
        return candidate

    monkeypatch.setattr(
        "app.connectors.factory.connector_for",
        lambda *a, **k: _SnippetConnector([unsafe], LIST_PAGE_HTML),
    )
    monkeypatch.setattr("app.connectors.common.fill_candidate_from_content", _capture)

    items = await _scrape_candidates(_Src())
    assert len(items) == 1
    assert captured[0]["html"] is None


# ── Connectors set snippet_html ──────────────────────────────────────────────


@pytest.fixture
def no_deep_fetch(monkeypatch):
    async def _identity(self, candidates):
        return candidates

    monkeypatch.setattr(GenericHtmlConnector, "_deep_fetch_candidates", _identity)
    monkeypatch.setattr(ConfigurableHtmlConnector, "_deep_fetch_candidates", _identity)


@pytest.mark.asyncio
async def test_generic_html_sets_snippet_html_from_card(no_deep_fetch):
    html = f"""
    <html><body>
      {CARD_HTML}
    </body></html>
    """
    raw = RawSourceResult(
        source_key="generic-snippet",
        url="https://example.gov.co/list",
        content=html,
        content_type="text/html",
    )
    candidates = await GenericHtmlConnector("generic-snippet", raw.url).parse(raw)
    assert len(candidates) >= 1
    match = next(c for c in candidates if "beca" in c.title.lower() or CARD_URL in c.official_url)
    assert match.snippet_html
    assert "beca" in match.snippet_html.lower() or "investig" in match.snippet_html.lower()
    assert is_safe_candidate_snippet(match.snippet_html, match.official_url)
    assert "<html" not in match.snippet_html.lower()


@pytest.mark.asyncio
async def test_configurable_html_sets_snippet_html_from_container(no_deep_fetch):
    html = f"""
    <html><body>
      <div class="views-row">
        <h2><a href="{CARD_URL}">Beca de investigación 2026</a></h2>
        <p>Convocatoria abierta. Elegibles: universidades públicas.</p>
      </div>
    </body></html>
    """
    config = HtmlConnectorConfig(
        list_selectors=[".views-row"],
        title_selectors=["h2", "a"],
        link_selectors=["a"],
        content_selectors=[".views-row"],
        date_labels=["Cierre:", "Deadline:"],
        detail_enrichment=False,
    )
    connector = ConfigurableHtmlConnector(
        "cfg-snippet",
        "https://example.gov.co/list",
        config,
    )
    raw = RawSourceResult(
        source_key="cfg-snippet",
        url="https://example.gov.co/list",
        content=html,
        content_type="text/html",
    )
    candidates = await connector.parse(raw)
    assert len(candidates) >= 1
    c = candidates[0]
    assert c.snippet_html
    assert "views-row" in c.snippet_html or "Beca" in c.snippet_html
    assert is_safe_candidate_snippet(c.snippet_html, c.official_url)
    assert "<html" not in c.snippet_html.lower()
