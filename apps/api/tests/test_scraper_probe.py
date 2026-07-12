"""Tests for app.scraper.probe — probe endpoint logic.

TDD Cycle: tests written FIRST, then probe.py implementation.

Covers:
- 4.4.1: GREEN — connector returns candidates > 0
- 4.4.2: YELLOW — connector returns 0 candidates
- 4.4.3: RED — connector.fetch() raises exception
- 4.4.4: source_key filter — only probe matching source
- 4.4.5: Timeout on fetch/parse within 15s
- 4.4.6: ProbeReport structure and counts
"""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_convocaradar.db")

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.db.seed import seed


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _seed():
    seed()


@pytest.fixture
def db(_seed):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_connector(fetch_result=None, parse_result=None, fetch_side_effect=None, parse_side_effect=None):
    """Build a mock connector object with async fetch/parse."""
    mock = MagicMock()
    mock.fetch = AsyncMock(return_value=fetch_result, side_effect=fetch_side_effect)
    mock.parse = AsyncMock(return_value=parse_result, side_effect=parse_side_effect)
    return mock


class FakeRawResult:
    """Minimal stand-in for connector fetch() return value."""
    def __init__(self, url="https://example.com/data", content_type="text/html", content="<html></html>"):
        self.url = url
        self.content_type = content_type
        self.content = content


class FakeCandidate:
    """Minimal stand-in for a parsed candidate."""
    def __init__(self, title="Test Opportunity"):
        self.title = title
        self.summary = ""
        self.entity = ""
        self.country = ""
        self.official_url = ""
        self.raw_text = ""
        self.categories = []
        self.topics = []
        self.language = "es"
        self.open_date = None
        self.close_date = None
        self.funding_amount_raw = None
        self.requirements = []
        self.confidence_score = 0.5


# ---------------------------------------------------------------------------
# Task 4.1 + 4.4 — Probe logic unit tests
# ---------------------------------------------------------------------------


async def test_probe_green_candidates_found(monkeypatch, db):
    """4.4.1: GREEN — connector returns candidates > 0."""
    from app.scraper.probe import run_probe

    connector = _make_mock_connector(
        fetch_result=FakeRawResult(),
        parse_result=[FakeCandidate(title="Grant A"), FakeCandidate(title="Grant B")],
    )

    def mock_connector_for(source_key, base_url=None, source_type=None, **kwargs):
        return connector

    monkeypatch.setattr("app.scraper.probe.connector_for", mock_connector_for)

    report = await run_probe(db)

    assert report.total == len(report.results)
    assert report.green >= 1
    assert report.yellow == 0
    assert report.red == 0
    # At least one GREEN result
    green_results = [r for r in report.results if r.status == "GREEN"]
    assert len(green_results) >= 1
    assert green_results[0].candidates_count > 0
    assert green_results[0].elapsed_seconds >= 0
    assert green_results[0].error_message is None


async def test_probe_yellow_zero_candidates(monkeypatch, db):
    """4.4.2: YELLOW — connector returns 0 candidates."""
    from app.scraper.probe import run_probe

    connector = _make_mock_connector(
        fetch_result=FakeRawResult(),
        parse_result=[],  # empty — 0 candidates
    )

    def mock_connector_for(source_key, base_url=None, source_type=None, **kwargs):
        return connector

    monkeypatch.setattr("app.scraper.probe.connector_for", mock_connector_for)

    report = await run_probe(db)

    assert report.yellow >= 1
    yellow_results = [r for r in report.results if r.status == "YELLOW"]
    assert len(yellow_results) >= 1
    assert yellow_results[0].candidates_count == 0
    assert yellow_results[0].error_message is None


async def test_probe_red_fetch_exception(monkeypatch, db):
    """4.4.3: RED — connector.fetch() raises an exception."""
    from app.scraper.probe import run_probe

    connector = _make_mock_connector(
        fetch_side_effect=ConnectionError("Connection refused"),
        parse_result=[],  # not reached
    )

    def mock_connector_for(source_key, base_url=None, source_type=None, **kwargs):
        return connector

    monkeypatch.setattr("app.scraper.probe.connector_for", mock_connector_for)

    report = await run_probe(db)

    assert report.red >= 1
    red_results = [r for r in report.results if r.status == "RED"]
    assert len(red_results) >= 1
    assert red_results[0].candidates_count is None
    assert red_results[0].error_message is not None


async def test_probe_source_key_filter(monkeypatch, db):
    """4.4.4: source_key filter — only probe matching source."""
    from app.scraper.probe import run_probe

    connector = _make_mock_connector(
        fetch_result=FakeRawResult(),
        parse_result=[FakeCandidate()],
    )

    call_log: list[str] = []

    def mock_connector_for(source_key, base_url=None, source_type=None, **kwargs):
        call_log.append(source_key)
        return connector

    monkeypatch.setattr("app.scraper.probe.connector_for", mock_connector_for)

    report = await run_probe(db, source_key=["minciencias"])

    # Only minciencias should be probed
    assert len(report.results) == 1
    assert report.results[0].source_key == "minciencias"
    assert report.total == 1


async def test_probe_report_structure(monkeypatch, db):
    """4.4.6: ProbeReport has all required fields."""
    from app.scraper.probe import run_probe

    connector = _make_mock_connector(
        fetch_result=FakeRawResult(),
        parse_result=[FakeCandidate()],
    )

    def mock_connector_for(source_key, base_url=None, source_type=None, **kwargs):
        return connector

    monkeypatch.setattr("app.scraper.probe.connector_for", mock_connector_for)

    report = await run_probe(db)

    assert report.total >= 1
    assert report.started_at is not None
    assert report.finished_at is not None
    assert report.started_at <= report.finished_at
    assert isinstance(report.green, int)
    assert isinstance(report.yellow, int)
    assert isinstance(report.red, int)
    assert report.green + report.yellow + report.red == report.total


async def test_probe_timeout_on_fetch(monkeypatch, db):
    """4.4.5: Timeout on fetch — connector.fetch() hangs → RED with timeout error."""
    import app.scraper.probe as probe_module

    monkeypatch.setattr(probe_module, "_PROBE_TIMEOUT", 0.1)
    from app.scraper.probe import run_probe

    async def hanging_fetch():
        await asyncio.sleep(999)  # never completes

    connector = _make_mock_connector(
        fetch_side_effect=hanging_fetch,
        parse_result=[],
    )

    def mock_connector_for(source_key, base_url=None, source_type=None, **kwargs):
        return connector

    monkeypatch.setattr("app.scraper.probe.connector_for", mock_connector_for)

    report = await run_probe(db, source_key=["minciencias"])

    assert report.red >= 1
    red_results = [r for r in report.results if r.status == "RED"]
    assert len(red_results) >= 1
    assert "timed out" in (red_results[0].error_message or "")
    assert red_results[0].candidates_count is None


async def test_probe_dataclass_serialization(monkeypatch, db):
    """ProbeResult and ProbeReport are serializable to dict."""
    from app.scraper.probe import ProbeResult, ProbeReport

    result = ProbeResult(
        source_key="test-source",
        status="GREEN",
        candidates_count=5,
        error_message=None,
        elapsed_seconds=1.23,
    )
    assert result.source_key == "test-source"
    assert result.status == "GREEN"
    assert result.candidates_count == 5

    now = datetime.now(UTC)
    report = ProbeReport(
        total=1,
        green=1,
        yellow=0,
        red=0,
        results=[result],
        started_at=now,
        finished_at=now,
    )
    d = {"total": report.total, "green": report.green, "results_count": len(report.results)}
    assert d["total"] == 1
    assert d["green"] == 1
    assert d["results_count"] == 1


# ═══════════════════════════════════════════════════════════════
# Connector-yellow-fixes: bancoldex and undp probe tests
# ═══════════════════════════════════════════════════════════════


def test_bancoldex_seed_definition_has_connector_config():
    """Verify bancoldex Source record includes connector_config after seeding."""
    from app.models import Source
    from sqlalchemy import select
    from app.db.session import SessionLocal

    session = SessionLocal()
    try:
        source = session.scalar(
            select(Source).where(Source.key == "bancoldex-convocatorias").limit(1)
        )
        assert source is not None, "bancoldex-convocatorias not found in seeded DB"
        cc = source.connector_config
        assert cc is not None, "bancoldex Source.connector_config is None"
        assert "list_selectors" in cc
        assert "tbody tr" in cc["list_selectors"]
        assert cc.get("detail_enrichment") is True
    finally:
        session.close()


def test_undp_seed_definition_has_connector_config():
    """Verify undp Source record includes connector_config after seeding."""
    from app.models import Source
    from sqlalchemy import select
    from app.db.session import SessionLocal

    session = SessionLocal()
    try:
        source = session.scalar(
            select(Source).where(Source.key == "undp-funding").limit(1)
        )
        assert source is not None, "undp-funding not found in seeded DB"
        cc = source.connector_config
        assert cc is not None, "undp Source.connector_config is None"
        assert "list_selectors" in cc
        assert "a.vacanciesTableLink.vacanciesTable__row" in cc["list_selectors"]
        assert cc.get("detail_enrichment") is True
    finally:
        session.close()


async def test_probe_bancoldex_returns_green(monkeypatch, db):
    """Probe for bancoldex-convocatorias returns GREEN when connector returns candidates."""
    from app.scraper.probe import run_probe

    connector = _make_mock_connector(
        fetch_result=FakeRawResult(),
        parse_result=[FakeCandidate(title="Invitación a Contratar 001")],
    )

    call_kwargs: dict = {}

    def mock_connector_for(source_key, base_url=None, source_type=None, **kwargs):
        call_kwargs.update(kwargs)
        return connector

    monkeypatch.setattr("app.scraper.probe.connector_for", mock_connector_for)

    report = await run_probe(db, source_key=["bancoldex-convocatorias"])

    assert len(report.results) == 1
    assert report.results[0].source_key == "bancoldex-convocatorias"
    assert report.results[0].status == "GREEN"
    assert report.results[0].candidates_count == 1
    assert report.green >= 1


async def test_probe_undp_returns_green(monkeypatch, db):
    """Probe for undp-funding returns GREEN when connector returns candidates."""
    from app.scraper.probe import run_probe

    connector = _make_mock_connector(
        fetch_result=FakeRawResult(),
        parse_result=[FakeCandidate(title="Procurement Notice 001")],
    )

    def mock_connector_for(source_key, base_url=None, source_type=None, **kwargs):
        return connector

    monkeypatch.setattr("app.scraper.probe.connector_for", mock_connector_for)

    report = await run_probe(db, source_key=["undp-funding"])

    assert len(report.results) == 1
    assert report.results[0].source_key == "undp-funding"
    assert report.results[0].status == "GREEN"
    assert report.results[0].candidates_count == 1
    assert report.green >= 1
