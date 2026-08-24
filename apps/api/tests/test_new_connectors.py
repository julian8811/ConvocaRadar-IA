"""Tests for 4 new connectors: ERC, COST, CARICOM, ASCUN."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.connectors.base import OpportunityCandidate, RawSourceResult
from app.connectors.cost_open_calls import CostOpenCallsConnector
from app.connectors.erc_calls import ErcCallsConnector
from app.connectors.caricom import CaricomConnector
from app.connectors.ascun import AscunConnector
from app.connectors.registry import registered_keys

# ── Fixture data ────────────────────────────────────────────────────────────

ERC_SAMPLE = """{"results": [{"identifier": "ERC-2026-StG", "title": "ERC Starting Grant 2026", "shortDescription": ["Funding for early-career researchers"], "contentDate": "2026-01-15T00:00:00.000Z", "deadlineDate": ["2026-10-15T00:00:00.000Z"]}]}"""
ERC_EMPTY = """{"results": []}"""
ERC_GARBAGE = "not json"

COST_SAMPLE = """[{"id": 1, "title": {"rendered": "Open Call for COST Action Proposals 2026"}, "link": "https://www.cost.eu/open-call-2026", "excerpt": {"rendered": "Apply for funding to coordinate research networks across Europe."}, "date": "2026-01-15T12:00:00"}]"""
COST_EMPTY = """[]"""
COST_GARBAGE = "not json"

CARICOM_SAMPLE = """<html><body><article><a href="/tenders/tender-1">Consultancy Services for Climate Resilience</a></article><article><a href="/tenders/tender-2">IT Infrastructure Upgrade for CARICOM Secretariat</a></article></body></html>"""
CARICOM_EMPTY = "<html><body></body></html>"
CARICOM_GARBAGE = "not useful content"

ASCUN_SAMPLE = """[{"id": 42, "title": {"rendered": "Convocatoria de Investigación 2026"}, "link": "https://ascun.org.co/convocatoria-2026", "excerpt": {"rendered": "Abierta convocatoria para proyectos de investigación."}, "date": "2026-03-01T10:00:00"}]"""
ASCUN_EMPTY = """[]"""
ASCUN_GARBAGE = "not json"


# ── Helpers ─────────────────────────────────────────────────────────────────


def _mock_fetch(monkeypatch, data: tuple[str, str, str]) -> AsyncMock:
    mock = AsyncMock()
    mock.return_value = data
    monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock)
    return mock


# ── ERC Tests ────────────────────────────────────────────────────────────────


class TestErcConnector:
    @pytest.mark.asyncio
    async def test_parse_sample(self):
        conn = ErcCallsConnector()
        raw = RawSourceResult(source_key="erc-calls", url="http://example.com", content=ERC_SAMPLE, content_type="application/json")
        candidates = await conn.parse(raw)
        assert len(candidates) >= 1
        assert "Starting Grant" in candidates[0].title

    @pytest.mark.asyncio
    async def test_parse_sample(self):
        conn = ErcCallsConnector()
        raw = RawSourceResult(source_key="erc-calls", url="http://example.com", content=ERC_SAMPLE, content_type="application/json")
        candidates = await conn.parse(raw)
        assert len(candidates) >= 1
        assert "Starting Grant" in candidates[0].title

    @pytest.mark.asyncio
    async def test_parse_empty(self):
        conn = ErcCallsConnector()
        raw = RawSourceResult(source_key="erc-calls", url="http://example.com", content=ERC_EMPTY, content_type="application/json")
        candidates = await conn.parse(raw)
        assert candidates == []

    @pytest.mark.asyncio
    async def test_parse_garbage(self):
        conn = ErcCallsConnector()
        raw = RawSourceResult(source_key="erc-calls", url="http://example.com", content=ERC_GARBAGE, content_type="application/json")
        candidates = await conn.parse(raw)
        assert isinstance(candidates, list)

    def test_registered(self):
        assert "erc-calls" in registered_keys()


# ── COST Tests ───────────────────────────────────────────────────────────────


class TestCostConnector:
    @pytest.mark.asyncio
    async def test_parse_sample(self):
        conn = CostOpenCallsConnector()
        raw = RawSourceResult(source_key="cost-open-calls", url="http://example.com", content=COST_SAMPLE, content_type="application/json")
        candidates = await conn.parse(raw)
        assert len(candidates) >= 1
        assert "Open Call" in candidates[0].title

    @pytest.mark.asyncio
    async def test_parse_empty(self):
        conn = CostOpenCallsConnector()
        raw = RawSourceResult(source_key="cost-open-calls", url="http://example.com", content=COST_EMPTY, content_type="application/json")
        candidates = await conn.parse(raw)
        assert candidates == []

    @pytest.mark.asyncio
    async def test_parse_garbage(self):
        conn = CostOpenCallsConnector()
        raw = RawSourceResult(source_key="cost-open-calls", url="http://example.com", content=COST_GARBAGE, content_type="application/json")
        candidates = await conn.parse(raw)
        assert isinstance(candidates, list)

    @pytest.mark.asyncio
    async def test_validate(self):
        conn = CostOpenCallsConnector()
        result = await conn.validate(OpportunityCandidate(title="Test", entity="COST", country="EU", official_url="https://www.cost.eu/test"))
        assert result.ok is True

    def test_registered(self):
        assert "cost-open-calls" in registered_keys()


# ── CARICOM Tests ────────────────────────────────────────────────────────────


class TestCaricomConnector:
    @pytest.mark.asyncio
    async def test_parse_sample(self):
        conn = CaricomConnector()
        raw = RawSourceResult(source_key="caricom-procurement", url="https://caricom.org/tenders", content=CARICOM_SAMPLE, content_type="text/html")
        candidates = await conn.parse(raw)
        assert len(candidates) >= 1
        assert any("Climate" in c.title for c in candidates)

    @pytest.mark.asyncio
    async def test_parse_empty(self):
        conn = CaricomConnector()
        raw = RawSourceResult(source_key="caricom-procurement", url="https://caricom.org/tenders", content=CARICOM_EMPTY, content_type="text/html")
        candidates = await conn.parse(raw)
        assert candidates == []

    @pytest.mark.asyncio
    async def test_parse_garbage(self):
        conn = CaricomConnector()
        raw = RawSourceResult(source_key="caricom-procurement", url="https://caricom.org/tenders", content=CARICOM_GARBAGE, content_type="text/html")
        candidates = await conn.parse(raw)
        assert isinstance(candidates, list)

    @pytest.mark.asyncio
    async def test_validate(self):
        conn = CaricomConnector()
        result = await conn.validate(OpportunityCandidate(title="Test", entity="CARICOM", country="International", official_url="https://caricom.org/tenders/tender-1"))
        assert result.ok is True

    def test_registered(self):
        assert "caricom-procurement" in registered_keys()


# ── ASCUN Tests ──────────────────────────────────────────────────────────────


class TestAscunConnector:
    @pytest.mark.asyncio
    async def test_parse_sample(self):
        conn = AscunConnector()
        raw = RawSourceResult(source_key="ascun-convocatorias", url="http://example.com", content=ASCUN_SAMPLE, content_type="application/json")
        candidates = await conn.parse(raw)
        assert len(candidates) >= 1
        assert "Investigación" in candidates[0].title

    @pytest.mark.asyncio
    async def test_parse_empty(self):
        conn = AscunConnector()
        raw = RawSourceResult(source_key="ascun-convocatorias", url="http://example.com", content=ASCUN_EMPTY, content_type="application/json")
        candidates = await conn.parse(raw)
        assert candidates == []

    @pytest.mark.asyncio
    async def test_parse_garbage(self, monkeypatch):
        _mock_fetch(monkeypatch, ("", ASCUN_GARBAGE, "application/json"))
        conn = AscunConnector()
        raw = await conn.fetch()
        candidates = await conn.parse(raw)
        assert isinstance(candidates, list)

    @pytest.mark.asyncio
    async def test_validate(self):
        conn = AscunConnector()
        result = await conn.validate(OpportunityCandidate(title="Test", entity="ASCUN", country="Colombia", official_url="https://ascun.org.co/convocatoria-2026"))
        assert result.ok is True

    def test_registered(self):
        assert "ascun-convocatorias" in registered_keys()
