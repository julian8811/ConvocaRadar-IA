"""E6: LLM extraction over rendered grants-gov detail pages.

grants-gov detail pages (search-results-detail/{id}) are JS shells in SSR:
plain-HTML enrichment cannot work, so unfunded grants-gov candidates get one
bounded Playwright render (existing ``render_page_html`` helper) followed by
the existing Gemini structured extraction, merged gap-fill-only via
``apply_extracted_fields``. Pilot-capped, best-effort, grants-gov only.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.connectors.base import OpportunityCandidate
from app.core.ai import AIExtraction


def _grants_candidate(**overrides) -> OpportunityCandidate:
    base = {
        "title": "Rural Innovation Grant",
        "entity": "USDA",
        "country": "United States",
        "official_url": "https://www.grants.gov/search-results-detail/99999",
        "summary": "Rural Innovation Grant",
        "raw_text": "Rural Innovation Grant",
        "confidence_score": 0.82,
    }
    base.update(overrides)
    return OpportunityCandidate(**base)


# Visible prose with NO digits, NO currency tokens and NO parseable dates, so
# the deterministic regex extractors find nothing and only the LLM can fill.
_RENDERED_PROSE_HTML = """<html><body><main>
<h1>Rural Innovation Grant</h1>
<div class="synopsis">
<p>This program supports rural small businesses developing clean energy
solutions across multiple states over several growing seasons.</p>
<p>The total award ceiling for each selected proposal is five hundred
thousand United States dollars, disbursed across consecutive project
periods subject to satisfactory progress reviews.</p>
<p>Applications for the autumn round are welcome from eligible rural
cooperatives and nonprofit organizations serving farming communities.</p>
</div>
</main></body></html>"""

_LLM_DATA = {
    "open_date": "2026-03-15",
    "close_date": "2026-09-30",
    "funding_amount_raw": "USD 500,000",
    "funding_amount_value": 500000.0,
    "funding_amount_currency": "USD",
}

_LLM_NULLS = {
    "open_date": None,
    "close_date": None,
    "funding_amount_raw": None,
    "funding_amount_value": None,
    "funding_amount_currency": None,
}


def _mock_render(monkeypatch, html: str = _RENDERED_PROSE_HTML):
    mock_render = AsyncMock()
    mock_render.side_effect = lambda url, **kwargs: (url, html, "text/html")
    monkeypatch.setattr("app.connectors.common.render_page_html", mock_render)
    return mock_render


def _mock_llm(monkeypatch, data: dict | None = None):
    mock_llm = AsyncMock()
    mock_llm.return_value = AIExtraction(
        data=dict(data if data is not None else _LLM_DATA),
        confidence=0.9,
        provider="google",
    )
    monkeypatch.setattr("app.core.ai.extract_opportunity_structured", mock_llm)
    return mock_llm


class TestGrantsGovRenderLlm:
    @pytest.mark.asyncio
    async def test_unfunded_candidate_gains_fields_via_render_llm(self, monkeypatch):
        """RED E6: render + LLM fills funding/dates the shell HTML cannot."""
        from app.connectors.common import enrich_grants_gov_render_llm

        mock_render = _mock_render(monkeypatch)
        mock_llm = _mock_llm(monkeypatch)

        (result,) = await enrich_grants_gov_render_llm([_grants_candidate()])

        assert result.funding_amount_value == 500000.0
        assert result.funding_amount_currency == "USD"
        assert result.funding_amount_raw is not None
        assert (result.close_date.year, result.close_date.month, result.close_date.day) == (
            2026,
            9,
            30,
        )
        assert (result.open_date.year, result.open_date.month, result.open_date.day) == (
            2026,
            3,
            15,
        )
        mock_render.assert_awaited_once()
        mock_llm.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_funded_candidate_skips_render_and_llm(self, monkeypatch):
        """Candidates that already have funding never cost a render."""
        from app.connectors.common import enrich_grants_gov_render_llm

        mock_render = _mock_render(monkeypatch)
        mock_llm = _mock_llm(monkeypatch)
        candidate = _grants_candidate(
            funding_amount_raw="USD 10,000",
            funding_amount_value=10000.0,
            funding_amount_currency="USD",
        )

        (result,) = await enrich_grants_gov_render_llm([candidate])

        assert result.funding_amount_value == 10000.0
        mock_render.assert_not_awaited()
        mock_llm.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_render_failure_degrades_to_current_behavior(self, monkeypatch):
        """A dead browser must degrade to the un-enriched candidate, never raise."""
        from app.connectors.common import enrich_grants_gov_render_llm

        mock_render = AsyncMock(side_effect=RuntimeError("Chromium crashed"))
        monkeypatch.setattr("app.connectors.common.render_page_html", mock_render)
        mock_llm = _mock_llm(monkeypatch)
        candidate = _grants_candidate()

        (result,) = await enrich_grants_gov_render_llm([candidate])

        assert result.funding_amount_value is None
        assert result.close_date is None
        mock_llm.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_existing_dates_never_overwritten(self, monkeypatch):
        """Gap-fill only: the list/API date wins over the LLM date."""
        from app.connectors.common import enrich_grants_gov_render_llm

        _mock_render(monkeypatch)
        _mock_llm(monkeypatch)
        candidate = _grants_candidate(close_date=datetime(2026, 10, 31))

        (result,) = await enrich_grants_gov_render_llm([candidate])

        assert result.close_date == datetime(2026, 10, 31)
        assert result.funding_amount_value == 500000.0

    @pytest.mark.asyncio
    async def test_render_cap_is_ten_per_run(self, monkeypatch):
        """Pilot cap: at most 10 renders no matter how many are unfunded."""
        from app.connectors.common import (
            GRANTS_GOV_RENDER_LLM_CAP,
            enrich_grants_gov_render_llm,
        )

        assert GRANTS_GOV_RENDER_LLM_CAP == 10
        mock_render = _mock_render(monkeypatch)
        _mock_llm(monkeypatch)
        candidates = [
            _grants_candidate(
                official_url=f"https://www.grants.gov/search-results-detail/{10000 + i}"
            )
            for i in range(12)
        ]

        result = await enrich_grants_gov_render_llm(candidates)

        assert mock_render.await_count == 10
        assert len(result) == 12
        assert [c.official_url for c in result] == [c.official_url for c in candidates]
        assert result[0].funding_amount_value == 500000.0
        assert result[11].funding_amount_value is None

    @pytest.mark.asyncio
    async def test_llm_nulls_leave_candidate_unchanged(self, monkeypatch):
        """No hallucination: null LLM fields must not fabricate values."""
        from app.connectors.common import enrich_grants_gov_render_llm

        _mock_render(monkeypatch)
        _mock_llm(monkeypatch, data=dict(_LLM_NULLS))

        (result,) = await enrich_grants_gov_render_llm([_grants_candidate()])

        assert result.funding_amount_value is None
        assert result.funding_amount_raw is None
        assert result.close_date is None
        assert result.open_date is None

    @pytest.mark.asyncio
    async def test_empty_render_skips_llm(self, monkeypatch):
        """An empty render yields no text, so no LLM call is spent."""
        from app.connectors.common import enrich_grants_gov_render_llm

        _mock_render(monkeypatch, html="")
        mock_llm = _mock_llm(monkeypatch)

        (result,) = await enrich_grants_gov_render_llm([_grants_candidate()])

        assert result.funding_amount_value is None
        mock_llm.assert_not_awaited()


class TestPilotHookScoping:
    @pytest.mark.asyncio
    async def test_pilot_hook_runs_render_llm_for_grants_gov(self, monkeypatch):
        """enrich_pilot_candidates('grants-gov') gap-fills shells via render+LLM."""
        from app.connectors.common import enrich_pilot_candidates

        shell = "<html><head></head><body><div id='root'></div></body></html>"
        mock_fetch = AsyncMock(return_value=("https://www.grants.gov/x", shell, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock_fetch)
        mock_render = _mock_render(monkeypatch)
        _mock_llm(monkeypatch)

        (result,) = await enrich_pilot_candidates("grants-gov", [_grants_candidate()])

        assert result.funding_amount_value == 500000.0
        mock_render.assert_awaited()

    @pytest.mark.asyncio
    async def test_pilot_hook_never_renders_other_sources(self, monkeypatch):
        """The render+LLM step is scoped to grants-gov only."""
        from app.connectors.common import enrich_pilot_candidates

        mock_fetch = AsyncMock(side_effect=RuntimeError("offline"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock_fetch)
        mock_render = _mock_render(monkeypatch)
        mock_llm = _mock_llm(monkeypatch)
        candidate = _grants_candidate(
            official_url="https://minciencias.gov.co/convocatorias/ciencia-2026"
        )

        result = await enrich_pilot_candidates("minciencias", [candidate])

        assert result[0].funding_amount_value is None
        mock_render.assert_not_awaited()
        mock_llm.assert_not_awaited()
