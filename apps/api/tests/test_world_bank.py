"""Tests for the World Bank procurement API connector."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.connectors.base import OpportunityCandidate, RawSourceResult
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
        assert c1.close_date is not None

        # Second candidate
        c2 = candidates[1]
        assert c2.title == "Rural Water Supply System"
        assert c2.country == "Peru"
        assert "Request for Proposals" in c2.categories

    @pytest.mark.asyncio
    async def test_parse_emits_past_dates_with_close_date(self, connector):
        raw = RawSourceResult(
            source_key="world-bank-procurement",
            url="http://example.com",
            content=_make_api_response(past_dates=True),
            content_type="application/json",
        )

        candidates = await connector.parse(raw)

        titles = [c.title for c in candidates]
        assert "Expired Road Construction" in titles
        assert len(candidates) == 3
        past = next(c for c in candidates if c.title == "Expired Road Construction")
        assert past.close_date is not None
        assert past.close_date < datetime.now()

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


# ── Rich field map (PR4) ───────────────────────────────────────────────────


def _rich_notice(*, past_deadline: bool = False) -> dict:
    now = datetime.now()
    future = (now + timedelta(days=45)).strftime("%Y-%m-%d")
    past = (now - timedelta(days=5)).strftime("%Y-%m-%d")
    deadline = past if past_deadline else future
    return {
        "id": "OP00123456",
        "bid_description": "Consulting Services for Climate Adaptation",
        "notice_type": "Invitation for Bids",
        "noticedate": f"{future}T00:00:00",
        "submission_deadline_date": f"{deadline}T23:59:59",
        "submission_date": f"{future}T12:00:00",
        "project_name": "Climate Resilience Project",
        "project_ctry_name": "Kenya",
        "project_id": "P123456",
        "bid_reference_no": "WB-KE-2026-01",
        "procurement_group": "Consulting Services",
        "procurement_method_code": "QCBS",
        "procurement_method_name": "Quality And Cost-Based Selection",
        "notice_text": "<p>Full notice body with <b>eligibility</b> details.</p>",
        "notice_status": "Published",
    }


class TestRichFieldMap:
    @pytest.mark.asyncio
    async def test_parse_maps_rich_procnotice_fields(self, connector):
        notice = _rich_notice()
        raw = RawSourceResult(
            source_key="world-bank-procurement",
            url="http://example.com",
            content=json.dumps({"total": 1, "rows": 1, "procnotices": {"OP00123456": notice}}),
            content_type="application/json",
        )

        candidates = await connector.parse(raw)
        assert len(candidates) == 1
        c = candidates[0]

        assert c.external_id == "OP00123456"
        assert c.title == "Consulting Services for Climate Adaptation"
        assert c.summary == "Climate Resilience Project"
        assert c.country == "Kenya"
        assert "eligibility" in (c.description or "").lower() or "eligibility" in c.raw_text.lower()
        assert "<p>" not in (c.description or "")
        assert "<p>" not in c.raw_text
        assert c.snippet_html is not None
        assert "<p>" in c.snippet_html
        assert c.open_date is not None
        assert c.open_date.strftime("%Y-%m-%d") == notice["noticedate"][:10]
        assert c.close_date is not None
        assert c.close_date.strftime("%Y-%m-%d") == notice["submission_deadline_date"][:10]
        assert "Invitation for Bids" in c.categories
        assert "Consulting Services" in c.categories
        assert "Quality And Cost-Based Selection" in c.categories
        assert "P123456" in c.topics
        assert "WB-KE-2026-01" in c.topics
        assert "QCBS" in c.topics
        assert (
            c.official_url
            == "https://projects.worldbank.org/en/projects-operations/procurement-detail/OP00123456"
        )

    @pytest.mark.asyncio
    async def test_parse_leaves_absent_optional_fields_unset(self, connector):
        minimal = {
            "id": "OP-MIN",
            "bid_description": "Minimal notice only",
            "submission_date": (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%dT23:59:59"),
        }
        raw = RawSourceResult(
            source_key="world-bank-procurement",
            url="http://example.com",
            content=json.dumps({"procnotices": {"OP-MIN": minimal}}),
            content_type="application/json",
        )

        candidates = await connector.parse(raw)
        assert len(candidates) == 1
        c = candidates[0]
        assert c.external_id == "OP-MIN"
        assert c.title == "Minimal notice only"
        assert c.summary == "Minimal notice only"
        assert c.open_date is None
        assert c.snippet_html is None
        # No notice_text → no HTML body; thin_fill may copy summary into description.
        assert "<" not in (c.description or "")
        assert c.description in ("", c.summary)
        assert c.close_date is not None

    @pytest.mark.asyncio
    async def test_parse_emits_past_deadline_with_deadline_date_preferred(self, connector):
        notice = _rich_notice(past_deadline=True)
        raw = RawSourceResult(
            source_key="world-bank-procurement",
            url="http://example.com",
            content=json.dumps({"procnotices": {notice["id"]: notice}}),
            content_type="application/json",
        )

        candidates = await connector.parse(raw)
        assert len(candidates) == 1
        past = candidates[0]
        assert past.close_date is not None
        assert past.close_date < datetime.now()
        assert past.close_date.strftime("%Y-%m-%d") == notice["submission_deadline_date"][:10]


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
