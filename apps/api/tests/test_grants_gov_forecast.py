"""Via A: grants-gov-forecast on keyless search2 with oppStatuses=forecasted.

Zero network: fetch_httpx_text is mocked; fixtures use the inline
search2 shape (data.oppHits).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.connectors.base import RawSourceResult


def _search2_content(hits: list[dict]) -> str:
    return json.dumps({"data": {"oppHits": hits}})


def _forecast_hit(**overrides: object) -> dict:
    hit: dict = {
        "id": "351001",
        "title": "Forecasted Research Grant",
        "agencyName": "National Science Foundation",
        "number": "NSF-26-100",
        "oppStatus": "forecasted",
        "synopsis": "Upcoming funding for research projects.",
        "openDate": "03/15/2026",
        "closeDate": "09/30/2026",
        "awardCeiling": "500000",
    }
    hit.update(overrides)
    return hit


def _posted_hit() -> dict:
    return _forecast_hit(
        id="351002",
        title="Posted Research Grant",
        number="NSF-26-101",
        oppStatus="posted",
    )


class TestGrantsGovForecastFetch:
    @pytest.mark.asyncio
    async def test_fetch_posts_forecasted_status_to_search2(self):
        from app.connectors.grants_gov import GrantsGovForecastConnector

        captured: dict = {}

        async def fake_fetch(url, **kwargs):
            captured["url"] = url
            captured["payload"] = kwargs.get("payload")
            captured["method"] = kwargs.get("method")
            return (url, _search2_content([_forecast_hit()]), "application/json")

        with patch(
            "app.connectors.grants_gov.fetch_httpx_text", side_effect=fake_fetch
        ):
            raw = await GrantsGovForecastConnector().fetch()

        assert captured["url"] == "https://api.grants.gov/v1/api/search2"
        assert captured["method"] == "POST"
        assert captured["payload"] is not None
        assert "forecasted" in str(captured["payload"].get("oppStatuses", ""))
        assert raw.content_type == "application/json"


class TestGrantsGovForecastParse:
    @pytest.mark.asyncio
    async def test_parse_keeps_only_forecasted_hits(self):
        from app.connectors.grants_gov import GrantsGovForecastConnector

        raw = RawSourceResult(
            source_key="grants-gov-forecast",
            url="https://api.grants.gov/v1/api/search2",
            content=_search2_content([_forecast_hit(), _posted_hit()]),
            content_type="application/json",
        )
        candidates = await GrantsGovForecastConnector().parse(raw)
        assert len(candidates) == 1
        assert candidates[0].title == "Forecasted Research Grant"
        assert candidates[0].official_url == (
            "https://www.grants.gov/search-results-detail/351001"
        )

    @pytest.mark.asyncio
    async def test_parse_empty_hits_returns_empty_without_network(self):
        from app.connectors.grants_gov import GrantsGovForecastConnector

        raw = RawSourceResult(
            source_key="grants-gov-forecast",
            url="https://api.grants.gov/v1/api/search2",
            content=_search2_content([]),
            content_type="application/json",
        )
        with patch(
            "app.connectors.grants_gov.fetch_httpx_text",
            new_callable=AsyncMock,
        ) as mock_fetch:
            # Empty hits fall back to the simpler search page; mock it empty.
            mock_fetch.return_value = (
                "https://simpler.grants.gov/search",
                "<html><body><p>No results</p></body></html>",
                "text/html",
            )
            candidates = await GrantsGovForecastConnector().parse(raw)
        assert candidates == []

    @pytest.mark.asyncio
    async def test_validate_accepts_grants_gov_detail_url(self):
        from app.connectors.grants_gov import GrantsGovForecastConnector

        raw = RawSourceResult(
            source_key="grants-gov-forecast",
            url="https://api.grants.gov/v1/api/search2",
            content=_search2_content([_forecast_hit()]),
            content_type="application/json",
        )
        (candidate,) = await GrantsGovForecastConnector().parse(raw)
        result = await GrantsGovForecastConnector().validate(candidate)
        assert result.ok is True


class TestGrantsGovForecastFactory:
    def test_factory_routes_forecast_to_search2_connector(self):
        from app.connectors.factory import connector_for
        from app.connectors.grants_gov import GrantsGovForecastConnector

        connector = connector_for(
            "grants-gov-forecast",
            "https://api.grants.gov/v1/api/search2",
            source_type="api",
        )
        assert isinstance(connector, GrantsGovForecastConnector)
        assert connector.source_key == "grants-gov-forecast"


class TestGrantsGovOperativeUnchanged:
    @pytest.mark.asyncio
    async def test_operative_connector_still_requests_posted(self):
        from app.connectors.grants_gov import GrantsGovConnector

        captured: dict = {}

        async def fake_fetch(url, **kwargs):
            captured["payload"] = kwargs.get("payload")
            return (url, _search2_content([_posted_hit()]), "application/json")

        with patch(
            "app.connectors.grants_gov.fetch_httpx_text", side_effect=fake_fetch
        ):
            await GrantsGovConnector().fetch()

        statuses = str(captured["payload"].get("oppStatuses", ""))
        assert "posted" in statuses
