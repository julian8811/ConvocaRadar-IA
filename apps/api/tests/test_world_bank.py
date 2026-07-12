"""Tests for the World Bank procurement API connector."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.connectors.base import OpportunityCandidate, RawSourceResult, ValidationResult
from app.connectors.registry import get_connector, registered_keys
from app.connectors.world_bank import WorldBankConnector


# ── Fixtures ──────────────────────────────────────────────────────────────


def _make_api_response(*, past_dates: bool = False) -> str:
    """Build a sample World Bank API JSON response."""
    now = datetime.now()
    future = (now + timedelta(days=30)).strftime("%Y-%m-%d")
    past = (now - timedelta(days=10)).strftime("%Y-%m-%d")

    items = {
        "WB-001": {
            "id": "WB-001",
            "bid_description": "Construction of School in District X",
            "notice_type": "Invitation for Bids",
            "submission_date": f"{future}T23:59:59",
            "project_name": "Education Infrastructure Project",
            "project_ctry_name": "Colombia",
            "notice_text": "<p>Full notice HTML for school construction</p>",
        },
        "WB-002": {
            "id": "WB-002",
            "bid_description": "Rural Water Supply System",
            "notice_type": "Request for Proposals",
            "submission_date": f"{future}T23:59:59",
            "project_name": "Water and Sanitation Project",
            "project_ctry_name": "Peru",
            "notice_text": "<p>Water system details</p>",
        },
    }

    if past_dates:
        items["WB-003"] = {
            "id": "WB-003",
            "bid_description": "Expired Road Construction",
            "notice_type": "Invitation for Bids",
            "submission_date": f"{past}T23:59:59",
            "project_name": "Highway Project",
            "project_ctry_name": "Brazil",
            "notice_text": "<p>Expired notice</p>",
        }

    return json.dumps({"total": len(items), "rows": len(items), "procnotices": items})


@pytest.fixture
def connector() -> WorldBankConnector:
    return WorldBankConnector()


@pytest.fixture
def mock_fetch(monkeypatch) -> AsyncMock:
    mock = AsyncMock()
    monkeypatch.setattr(
        "app.connectors.world_bank.fetch_httpx_text",
        mock,
    )
    return mock


# ── fetch tests ────────────────────────────────────────────────────────────


class TestFetch:
    @pytest.mark.asyncio
    async def test_fetch_returns_raw_source_result(self, connector, mock_fetch):
        mock_fetch.return_value = (
            "https://search.worldbank.org/api/v2/procnotices?format=json&rows=100&srt=submission_date desc&order=desc",
            _make_api_response(),
            "application/json",
        )

        result = await connector.fetch()

        assert isinstance(result, RawSourceResult)
        assert result.source_key == "world-bank-procurement"
        assert result.content_type == "application/json"
        assert result.content
        assert "WB-001" in result.content

    @pytest.mark.asyncio
    async def test_fetch_uses_correct_url(self, connector, mock_fetch):
        mock_fetch.return_value = ("", "{}", "application/json")

        await connector.fetch()

        mock_fetch.assert_awaited_once()
        call_url = mock_fetch.await_args[0][0]
        assert "format=json" in call_url
        assert "rows=100" in call_url
        assert "srt=submission_date desc" in call_url
        assert "order=desc" in call_url
        assert "search.worldbank.org" in call_url


# ── parse tests ───────────────────────────────────────────────────────────


class TestParse:
    @pytest.mark.asyncio
    async def test_parse_maps_items_to_candidates(self, connector):
        raw = RawSourceResult(
            source_key="world-bank-procurement",
            url="http://example.com",
            content=_make_api_response(),
            content_type="application/json",
        )

        candidates = await connector.parse(raw)

        assert len(candidates) == 2
        assert all(isinstance(c, OpportunityCandidate) for c in candidates)

        # First candidate
        c1 = candidates[0]
        assert c1.title == "Construction of School in District X"
        assert c1.entity == "World Bank"
        assert c1.country == "Colombia"
        assert (
            c1.official_url
            == "https://projects.worldbank.org/en/projects-operations/procurement-detail/WB-001"
        )
        assert c1.summary == "Education Infrastructure Project"
        assert "Invitation for Bids" in c1.categories
        assert "procurement" in c1.categories
        assert c1.topics == ["world-bank-procurement"]
        assert c1.close_date is not None

        # Second candidate
        c2 = candidates[1]
        assert c2.title == "Rural Water Supply System"
        assert c2.country == "Peru"
        assert "Request for Proposals" in c2.categories

    @pytest.mark.asyncio
    async def test_parse_filters_out_past_dates(self, connector):
        raw = RawSourceResult(
            source_key="world-bank-procurement",
            url="http://example.com",
            content=_make_api_response(past_dates=True),
            content_type="application/json",
        )

        candidates = await connector.parse(raw)

        # WB-003 (past date) should be filtered out
        titles = [c.title for c in candidates]
        assert "Expired Road Construction" not in titles
        assert len(candidates) == 2

    @pytest.mark.asyncio
    async def test_parse_handles_empty_response(self, connector):
        raw = RawSourceResult(
            source_key="world-bank-procurement",
            url="http://example.com",
            content="{}",
            content_type="application/json",
        )

        candidates = await connector.parse(raw)
        assert candidates == []

    @pytest.mark.asyncio
    async def test_parse_handles_garbage(self, connector):
        raw = RawSourceResult(
            source_key="world-bank-procurement",
            url="http://example.com",
            content="not json at all",
            content_type="application/json",
        )

        candidates = await connector.parse(raw)
        assert candidates == []

    @pytest.mark.asyncio
    async def test_parse_handles_missing_bid_description(self, connector):
        data = {
            "total": 1,
            "rows": 1,
            "procnotices": {
                "WB-999": {
                    "id": "WB-999",
                    "bid_description": "",
                    "notice_type": "Invitation for Bids",
                },
            },
        }
        raw = RawSourceResult(
            source_key="world-bank-procurement",
            url="http://example.com",
            content=json.dumps(data),
            content_type="application/json",
        )

        candidates = await connector.parse(raw)
        assert candidates == []

    @pytest.mark.asyncio
    async def test_parse_handles_missing_procnotices_key(self, connector):
        raw = RawSourceResult(
            source_key="world-bank-procurement",
            url="http://example.com",
            content=json.dumps({"total": 0}),
            content_type="application/json",
        )

        candidates = await connector.parse(raw)
        assert candidates == []


# ── validate tests ────────────────────────────────────────────────────────


class TestValidate:
    @pytest.mark.asyncio
    async def test_validate_passes_valid_candidate(self, connector):
        candidate = OpportunityCandidate(
            title="School Construction",
            entity="World Bank",
            country="Colombia",
            official_url="https://projects.worldbank.org/en/projects-operations/procurement-detail/WB-001",
        )

        result = await connector.validate(candidate)
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_validate_rejects_missing_title(self, connector):
        candidate = OpportunityCandidate(
            title="",
            entity="World Bank",
            country="Colombia",
            official_url="https://projects.worldbank.org/en/projects-operations/procurement-detail/WB-001",
        )

        result = await connector.validate(candidate)
        assert result.ok is False
        assert "Missing title" in result.reason

    @pytest.mark.asyncio
    async def test_validate_rejects_non_world_bank_url(self, connector):
        candidate = OpportunityCandidate(
            title="School Construction",
            entity="World Bank",
            country="Colombia",
            official_url="https://evil.com/scam",
        )

        result = await connector.validate(candidate)
        assert result.ok is False
        assert "official url" in result.reason.lower()


# ── Registration tests ────────────────────────────────────────────────────


class TestRegistration:
    def test_connector_is_registered(self):
        assert "world-bank-procurement" in registered_keys()

    def test_get_connector_returns_world_bank_instance(self):
        connector = get_connector("world-bank-procurement")
        assert isinstance(connector, WorldBankConnector)
        assert connector.source_key == "world-bank-procurement"

    def test_connector_for_uses_registry(self):
        from app.connectors.factory import connector_for

        connector = connector_for("world-bank-procurement", "http://example.com")
        assert isinstance(connector, WorldBankConnector)
