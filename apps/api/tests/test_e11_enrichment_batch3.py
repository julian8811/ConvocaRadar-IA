"""E11: enrichment batch 3 — fapesp-brasil (SSR batch), developmentaid (render), cost dictamen.

- fapesp-brasil detail pages are full SSR text and deterministic extractors
  already yield dates from it, so the key joins the runner-level pilot gate
  and the existing SSR batch path covers it (no dedicated connector file).
- developmentaid-tenders plain fetch hits a Cloudflare challenge, but a
  bounded Chromium render passes it, so it gets a key-gated render-based
  detail step (render_page_html + extract_page_fields + apply_extracted_fields,
  capped, best-effort never-raises, gap-fill only).
- cost-open-calls gets a DICTAMEN (no code): stored rows point at site-nav
  junk URLs, a parse-quality problem outside enrichment scope.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.connectors.base import OpportunityCandidate


def _fapesp_candidate(**overrides) -> OpportunityCandidate:
    base = {
        "title": "Bolsa de pesquisa FAPESP",
        "entity": "FAPESP",
        "country": "Brazil",
        "official_url": "https://fapesp.br/oportunidades/bolsa-12345/",
        "summary": "Bolsa de pesquisa FAPESP",
        "raw_text": "Bolsa de pesquisa FAPESP",
        "confidence_score": 0.55,
    }
    base.update(overrides)
    return OpportunityCandidate(**base)


def _developmentaid_candidate(**overrides) -> OpportunityCandidate:
    base = {
        "title": "Caribbean Efficient And Green Energy Buildings Project",
        "entity": "DevelopmentAid",
        "country": "",
        "official_url": "https://www.developmentaid.org/tenders/view/1685752/caribbean-project",
        "summary": "Sitemap entry",
        "raw_text": "https://www.developmentaid.org/tenders/view/1685752/caribbean-project",
        "confidence_score": 0.45,
        "open_date": datetime(2026, 8, 20),
    }
    base.update(overrides)
    return OpportunityCandidate(**base)


# SSR detail body in the shape parent verified live (full text, open+close dates).
_FAPESP_DETAIL_HTML = """<html><body><main>
<h1>Bolsa de pesquisa FAPESP</h1>
<div class="content">
<p>Abertura: 17/09/2026</p>
<p>Inscrições até 07/10/2026</p>
<p>Valor da bolsa: R$ 5.000,00 mensais</p>
</div>
</main></body></html>"""

# Rendered DevelopmentAid Angular SSR detail fragment.
_DEVAID_RENDERED_HTML = """<html><body><main>
<h1 class="name">Caribbean Efficient and Green Energy Buildings Project</h1>
<div class="details">
<span>Location:</span><span>Jamaica</span>
<span>Status:</span><span>Open</span>
<span>Posted:</span><span>20/08/2026</span>
<p>Submission deadline: 15/12/2026. Budget: USD 250,000.</p>
</div>
</main></body></html>"""


def _mock_render(monkeypatch, html: str = _DEVAID_RENDERED_HTML):
    mock_render = AsyncMock()
    mock_render.side_effect = lambda url, **kwargs: (url, html, "text/html")
    monkeypatch.setattr("app.connectors.common.render_page_html", mock_render)
    return mock_render


class TestPilotGateBatch3:
    def test_gate_holds_fapesp_and_developmentaid_not_cost(self):
        """RED E11: fapesp-brasil + developmentaid-tenders join the gate; cost stays out."""
        from app.connectors.common import DETAIL_ENRICHMENT_PILOT_KEYS

        assert "fapesp-brasil" in DETAIL_ENRICHMENT_PILOT_KEYS
        assert "developmentaid-tenders" in DETAIL_ENRICHMENT_PILOT_KEYS
        assert "cost-open-calls" not in DETAIL_ENRICHMENT_PILOT_KEYS
        # Earlier pilots unchanged.
        assert "grants-gov" in DETAIL_ENRICHMENT_PILOT_KEYS
        assert "innpulsa" in DETAIL_ENRICHMENT_PILOT_KEYS
        assert "minciencias" in DETAIL_ENRICHMENT_PILOT_KEYS

    @pytest.mark.asyncio
    async def test_fapesp_candidate_gains_dates_from_ssr_batch(self, monkeypatch):
        """RED E11: fapesp-brasil enriches through the existing SSR batch path."""
        from app.connectors.common import enrich_pilot_candidates

        mock_fetch = AsyncMock(
            return_value=("https://fapesp.br/oportunidades/bolsa-12345/", _FAPESP_DETAIL_HTML, "text/html")
        )
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock_fetch)

        (result,) = await enrich_pilot_candidates("fapesp-brasil", [_fapesp_candidate()])

        assert result.close_date is not None
        assert (result.close_date.year, result.close_date.month, result.close_date.day) == (
            2026,
            10,
            7,
        )
        assert result.open_date is not None
        mock_fetch.assert_awaited()

    @pytest.mark.asyncio
    async def test_cost_passthrough_makes_no_fetch_and_no_render(self, monkeypatch):
        """DICTAMEN pin: cost-open-calls skips enrichment entirely (parse-quality issue)."""
        from app.connectors.common import enrich_pilot_candidates

        mock_fetch = AsyncMock()
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock_fetch)
        mock_render = _mock_render(monkeypatch)
        candidate = OpportunityCandidate(
            title="COST Open Call",
            entity="COST Association",
            country="European Union",
            official_url="https://www.cost.eu/am-i-eligible/",
            summary="COST Open Call",
            raw_text="COST Open Call",
            confidence_score=0.55,
        )

        result = await enrich_pilot_candidates("cost-open-calls", [candidate])

        assert result == [candidate]
        mock_fetch.assert_not_awaited()
        mock_render.assert_not_awaited()


class TestDevelopmentaidRender:
    @pytest.mark.asyncio
    async def test_unfunded_candidate_gains_fields_via_render(self, monkeypatch):
        """RED E11: render fills close date the CF-blocked fetch cannot."""
        from app.connectors.common import enrich_developmentaid_render

        mock_render = _mock_render(monkeypatch)
        mock_fetch = AsyncMock()
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock_fetch)

        (result,) = await enrich_developmentaid_render([_developmentaid_candidate()])

        assert result.close_date is not None
        assert (result.close_date.year, result.close_date.month, result.close_date.day) == (
            2026,
            12,
            15,
        )
        # Sitemap open_date (lastmod) is preserved — gap-fill only.
        assert result.open_date == datetime(2026, 8, 20)
        mock_render.assert_awaited_once()
        mock_fetch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_pilot_hook_uses_render_not_plain_fetch(self, monkeypatch):
        """RED E11: the pilot hook routes developmentaid to render (plain fetch is CF-blocked)."""
        from app.connectors.common import enrich_pilot_candidates

        mock_render = _mock_render(monkeypatch)
        mock_fetch = AsyncMock()
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock_fetch)

        (result,) = await enrich_pilot_candidates(
            "developmentaid-tenders", [_developmentaid_candidate()]
        )

        assert result.close_date is not None
        mock_render.assert_awaited()
        mock_fetch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fully_enriched_candidate_skips_render(self, monkeypatch):
        """Candidates with nothing missing never cost a render."""
        from app.connectors.common import enrich_developmentaid_render

        mock_render = _mock_render(monkeypatch)
        candidate = _developmentaid_candidate(
            close_date=datetime(2026, 12, 15),
            funding_amount_raw="USD 250,000",
            funding_amount_value=250000.0,
            funding_amount_currency="USD",
        )

        (result,) = await enrich_developmentaid_render([candidate])

        assert result.funding_amount_value == 250000.0
        mock_render.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_render_failure_degrades_to_current_behavior(self, monkeypatch):
        """A dead browser must degrade to the un-enriched candidate, never raise."""
        from app.connectors.common import enrich_developmentaid_render

        mock_render = AsyncMock(side_effect=RuntimeError("Chromium crashed"))
        monkeypatch.setattr("app.connectors.common.render_page_html", mock_render)

        (result,) = await enrich_developmentaid_render([_developmentaid_candidate()])

        assert result.close_date is None
        assert result.open_date == datetime(2026, 8, 20)

    @pytest.mark.asyncio
    async def test_challenge_remnant_yields_no_fields(self, monkeypatch):
        """A render that still shows the CF challenge must not fabricate fields."""
        from app.connectors.common import enrich_developmentaid_render

        _mock_render(
            monkeypatch,
            html="<html><head><title>Just a moment...</title></head>"
            "<body><div>Just a moment... verifying you are human Cloudflare</div></body></html>",
        )

        (result,) = await enrich_developmentaid_render([_developmentaid_candidate()])

        assert result.close_date is None
        assert result.funding_amount_value is None

    @pytest.mark.asyncio
    async def test_render_cap_is_five_per_run(self, monkeypatch):
        """Pilot cap: at most 5 renders no matter how many need enrichment."""
        from app.connectors.common import (
            DEVELOPMENTAID_RENDER_CAP,
            enrich_developmentaid_render,
        )

        assert DEVELOPMENTAID_RENDER_CAP == 5
        mock_render = _mock_render(monkeypatch)
        candidates = [
            _developmentaid_candidate(
                official_url=f"https://www.developmentaid.org/tenders/view/{10000 + i}/project-{i}"
            )
            for i in range(7)
        ]

        result = await enrich_developmentaid_render(candidates)

        assert mock_render.await_count == 5
        assert len(result) == 7
        assert [c.official_url for c in result] == [c.official_url for c in candidates]
        assert result[0].close_date is not None
        assert result[6].close_date is None

    @pytest.mark.asyncio
    async def test_existing_close_date_never_overwritten(self, monkeypatch):
        """Gap-fill only: the sitemap/API date wins over the rendered date."""
        from app.connectors.common import enrich_developmentaid_render

        _mock_render(monkeypatch)
        candidate = _developmentaid_candidate(close_date=datetime(2026, 11, 30))

        (result,) = await enrich_developmentaid_render([candidate])

        assert result.close_date == datetime(2026, 11, 30)
