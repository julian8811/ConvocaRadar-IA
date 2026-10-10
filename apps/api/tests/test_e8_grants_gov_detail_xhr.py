"""E8: grants-gov detail XHR award gap-fill.

The search2 list API returns hits WITHOUT award fields, and the detail HTML
(SSR and rendered) is a JS shell without amounts. The real detail data comes
from a keyless endpoint::

    POST https://apply07.grants.gov/grantsws/rest/opportunity/details
    Content-Type: application/x-www-form-urlencoded;charset=UTF-8
    Referer: https://www.grants.gov/
    body: oppId={id} (form-encoded)

which returns JSON containing ``awardCeiling``, ``awardFloor``,
``awardCeilingFormatted``, ``awardFloorFormatted`` and ``estimatedFunding``.
Candidates still missing funding after the search-hit parse get a bounded,
best-effort XHR gap-fill mapped through the existing funding extractor.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.connectors.base import OpportunityCandidate


def _unfunded_candidate(**overrides) -> OpportunityCandidate:
    base = {
        "title": "Rural Innovation Grant",
        "entity": "USDA",
        "country": "United States",
        "official_url": "https://www.grants.gov/search-results-detail/351234",
        "summary": "Rural Innovation Grant",
        "raw_text": "Rural Innovation Grant",
        "confidence_score": 0.82,
        "external_id": "351234",
    }
    base.update(overrides)
    return OpportunityCandidate(**base)


_DETAIL_PAYLOAD = {
    "oppId": "351234",
    "oppTitle": "Rural Innovation Grant",
    "oppNumber": "USDA-2026-001",
    "awardCeiling": "750000",
    "awardCeilingFormatted": "$750,000",
    "awardFloor": "100000",
    "awardFloorFormatted": "$100,000",
    "estimatedFunding": "$750,000",
    "synopsisDesc": "Supports rural small businesses developing clean energy solutions.",
}


def _mock_detail(monkeypatch, payload: dict | None = None):
    mock_fetch = AsyncMock(return_value=dict(payload if payload is not None else _DETAIL_PAYLOAD))
    monkeypatch.setattr("app.connectors.grants_gov._fetch_grants_gov_detail", mock_fetch)
    return mock_fetch


class TestDetailFundingMapping:
    @pytest.mark.asyncio
    async def test_numeric_ceiling_maps_to_funding_value(self, monkeypatch):
        """RED E8: canned XHR payload fills funding_* on an unfunded candidate."""
        from app.connectors.grants_gov import enrich_grants_gov_funding_xhr

        _mock_detail(monkeypatch)

        (result,) = await enrich_grants_gov_funding_xhr([_unfunded_candidate()])

        assert result.funding_amount_value == 750000.0
        assert result.funding_amount_currency == "USD"
        assert result.funding_amount_raw is not None

    @pytest.mark.asyncio
    async def test_formatted_only_payload_still_maps(self, monkeypatch):
        """Formatted variants alone must map when numeric keys are absent."""
        from app.connectors.grants_gov import enrich_grants_gov_funding_xhr

        _mock_detail(
            monkeypatch,
            {"oppId": "351234", "awardCeilingFormatted": "$750,000"},
        )

        (result,) = await enrich_grants_gov_funding_xhr([_unfunded_candidate()])

        assert result.funding_amount_value == 750000.0
        assert result.funding_amount_currency == "USD"

    @pytest.mark.asyncio
    async def test_missing_award_fields_leave_candidate_unchanged(self, monkeypatch):
        """A detail payload with no award keys must not fabricate funding."""
        from app.connectors.grants_gov import enrich_grants_gov_funding_xhr

        _mock_detail(monkeypatch, {"oppId": "351234", "oppTitle": "No Money Here"})

        (result,) = await enrich_grants_gov_funding_xhr([_unfunded_candidate()])

        assert result.funding_amount_value is None
        assert result.funding_amount_raw is None
        assert result.funding_amount_currency is None


class TestGapFillSemantics:
    @pytest.mark.asyncio
    async def test_existing_funding_never_overwritten(self, monkeypatch):
        """Gap-fill only: funded candidates skip the XHR entirely."""
        from app.connectors.grants_gov import enrich_grants_gov_funding_xhr

        mock_fetch = _mock_detail(monkeypatch)
        candidate = _unfunded_candidate(
            funding_amount_raw="USD 10,000",
            funding_amount_value=10000.0,
            funding_amount_currency="USD",
        )

        (result,) = await enrich_grants_gov_funding_xhr([candidate])

        assert result.funding_amount_value == 10000.0
        assert result.funding_amount_raw == "USD 10,000"
        mock_fetch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_existing_dates_never_overwritten(self, monkeypatch):
        """The list/API dates win; XHR only fills funding gaps."""
        from datetime import datetime

        from app.connectors.grants_gov import enrich_grants_gov_funding_xhr

        _mock_detail(monkeypatch)
        candidate = _unfunded_candidate(close_date=datetime(2026, 10, 31))

        (result,) = await enrich_grants_gov_funding_xhr([candidate])

        assert result.close_date == datetime(2026, 10, 31)
        assert result.funding_amount_value == 750000.0

    @pytest.mark.asyncio
    async def test_http_error_degrades_to_current_behavior(self, monkeypatch):
        """A dead XHR endpoint degrades to the un-enriched candidate, never raises."""
        from app.connectors.grants_gov import enrich_grants_gov_funding_xhr

        mock_fetch = AsyncMock(return_value=None)
        monkeypatch.setattr("app.connectors.grants_gov._fetch_grants_gov_detail", mock_fetch)
        candidate = _unfunded_candidate()

        (result,) = await enrich_grants_gov_funding_xhr([candidate])

        assert result.funding_amount_value is None
        assert result.title == candidate.title
        mock_fetch.assert_awaited_once()


class TestCapBehavior:
    @pytest.mark.asyncio
    async def test_xhr_cap_bounds_fetches_per_run(self, monkeypatch):
        """Per-run cap: at most GRANTS_GOV_DETAIL_XHR_CAP fetches, order preserved."""
        from app.connectors.grants_gov import (
            GRANTS_GOV_DETAIL_XHR_CAP,
            enrich_grants_gov_funding_xhr,
        )

        assert GRANTS_GOV_DETAIL_XHR_CAP == 25
        mock_fetch = _mock_detail(monkeypatch)
        candidates = [
            _unfunded_candidate(
                official_url=f"https://www.grants.gov/search-results-detail/{400000 + i}",
                external_id=str(400000 + i),
            )
            for i in range(GRANTS_GOV_DETAIL_XHR_CAP + 5)
        ]

        result = await enrich_grants_gov_funding_xhr(candidates)

        assert mock_fetch.await_count == GRANTS_GOV_DETAIL_XHR_CAP
        assert len(result) == GRANTS_GOV_DETAIL_XHR_CAP + 5
        assert [c.official_url for c in result] == [c.official_url for c in candidates]
        assert result[0].funding_amount_value == 750000.0
        assert result[GRANTS_GOV_DETAIL_XHR_CAP].funding_amount_value is None
