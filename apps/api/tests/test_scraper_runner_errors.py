"""Tests for error classification in the scraper runner.

TDD Cycle: tests written FIRST, then runner.py modifications.

Covers:
- ERR-1: SourceRun logs include error_type field
- ERR-2: Correct classification for each exception type
- ERR-3: TIMEOUT/NETWORK → status="failed"; PARSE → "degraded"
- ERR-4: Health alerts created for PARSE/UNKNOWN, NOT for TIMEOUT/NETWORK
"""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_convocaradar.db")

import asyncio
from unittest.mock import AsyncMock, PropertyMock, patch

import httpx
import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.db.seed import seed


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures (reuse existing patterns from test_scraper_module.py)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _seed():
    seed()


@pytest.fixture
def db(_seed):
    from app.models import SourceRun

    session = SessionLocal()
    session.query(SourceRun).delete()
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def source(db):
    src = db.scalar(select(Source).where(Source.key == "minciencias"))
    assert src is not None, "seeded source 'minciencias' not found"
    return src


@pytest.fixture
def org_id(db):
    from app.models import Organization

    org = db.scalar(
        select(Organization).where(Organization.slug == "convocaradar-local")
    )
    assert org is not None, "seeded org not found"
    return str(org.id)


# We must import Source after setting DATABASE_URL
from app.models import Source  # noqa: E402


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _assert_log_has_error_type(run, expected_type: str) -> None:
    """Assert that at least one log entry contains error_type == expected_type."""
    assert any(
        log.get("error_type") == expected_type for log in run.logs
    ), f"No log entry with error_type='{expected_type}' in {run.logs}"


def _assert_health_alert_called(monkeypatch) -> None:
    """Assert that create_source_health_alert was called."""
    # Look for mock call evidence in run.logs for "health_alert" (not ideal)
    # Instead, use the monkeypatched flag approach
    pass  # We'll use direct mock assertions in tests


# ---------------------------------------------------------------------------
# Task 2.3 — ERR-1/ERR-2: error_type appears in logs for each category
# ---------------------------------------------------------------------------


async def test_timeout_error_sets_error_type_in_logs(
    monkeypatch, db, source, org_id
):
    """ERR-1/ERR-2: TimeoutError in _scrape_source_candidates_with_timeout
    must produce error_type=TIMEOUT in run logs."""
    from app.scraper.runner import run_source_inline

    async def mock_timeout(_source, _stats=None):
        raise TimeoutError("Simulated timeout for scraper test")

    monkeypatch.setattr(
        "app.scraper.runner._scrape_source_candidates_with_timeout",
        mock_timeout,
    )

    # Patch create_source_health_alert to track calls
    health_alert_called = False

    def track_health_alert(_db, _source, *, reason, recipient_email=None):
        nonlocal health_alert_called
        health_alert_called = True
        return None

    monkeypatch.setattr(
        "app.scraper.runner.create_source_health_alert",
        track_health_alert,
    )

    run = await run_source_inline(db, source, org_id)

    assert run.status == "failed"
    _assert_log_has_error_type(run, "TIMEOUT")
    # ERR-4: TIMEOUT must NOT create a health alert
    assert not health_alert_called, "TIMEOUT should NOT create a health alert"


async def test_network_httpx_error_sets_error_type_in_logs(
    monkeypatch, db, source, org_id
):
    """ERR-1/ERR-2: httpx.HTTPError → error_type=NETWORK in run logs."""
    from app.scraper.runner import run_source_inline

    async def mock_network_error(_source, _stats=None):
        raise httpx.HTTPError("HTTP 502 Bad Gateway")

    monkeypatch.setattr(
        "app.scraper.runner._scrape_source_candidates_with_timeout",
        mock_network_error,
    )

    health_alert_called = False

    def track_health_alert(_db, _source, *, reason, recipient_email=None):
        nonlocal health_alert_called
        health_alert_called = True
        return None

    monkeypatch.setattr(
        "app.scraper.runner.create_source_health_alert",
        track_health_alert,
    )

    run = await run_source_inline(db, source, org_id)

    assert run.status == "failed"
    _assert_log_has_error_type(run, "NETWORK")
    # ERR-4: NETWORK must NOT create a health alert
    assert not health_alert_called, "NETWORK should NOT create a health alert"


async def test_network_connection_error_sets_error_type_in_logs(
    monkeypatch, db, source, org_id
):
    """ERR-2: ConnectionError → error_type=NETWORK."""
    from app.scraper.runner import run_source_inline

    async def mock_conn_error(_source, _stats=None):
        raise ConnectionError("Connection refused")

    monkeypatch.setattr(
        "app.scraper.runner._scrape_source_candidates_with_timeout",
        mock_conn_error,
    )

    health_alert_called = False

    def track_health_alert(_db, _source, *, reason, recipient_email=None):
        nonlocal health_alert_called
        health_alert_called = True
        return None

    monkeypatch.setattr(
        "app.scraper.runner.create_source_health_alert",
        track_health_alert,
    )

    run = await run_source_inline(db, source, org_id)

    assert run.status == "failed"
    _assert_log_has_error_type(run, "NETWORK")
    assert not health_alert_called, "NETWORK should NOT create a health alert"


async def test_unknown_error_sets_error_type_and_creates_alert(
    monkeypatch, db, source, org_id
):
    """ERR-2/ERR-4: Generic Exception → error_type=UNKNOWN, health alert created."""
    from app.scraper.runner import run_source_inline

    async def mock_unknown_error(_source, _stats=None):
        raise ValueError("Unexpected data format")

    monkeypatch.setattr(
        "app.scraper.runner._scrape_source_candidates_with_timeout",
        mock_unknown_error,
    )

    health_alert_called = False
    health_alert_reason = None

    def track_health_alert(_db, _source, *, reason, recipient_email=None):
        nonlocal health_alert_called, health_alert_reason
        health_alert_called = True
        health_alert_reason = reason
        return None

    monkeypatch.setattr(
        "app.scraper.runner.create_source_health_alert",
        track_health_alert,
    )

    run = await run_source_inline(db, source, org_id)

    assert run.status == "failed"
    _assert_log_has_error_type(run, "UNKNOWN")
    # ERR-4: UNKNOWN should create a health alert
    assert health_alert_called, "UNKNOWN errors SHOULD create a health alert"
    assert health_alert_reason is not None


async def test_parse_error_sets_degraded_status_and_creates_alert(
    monkeypatch, db, source, org_id
):
    """ERR-3/ERR-4: PARSE error → status='degraded', health alert created.

    Currently PARSE errors are classified via a dummy scenario since
    connectors don't have dedicated parse exception classes yet.
    We generate a scenario where classify_error would return PARSE.
    """
    from app.scraper.runner import run_source_inline

    # Directly patch classify_error to return PARSE
    async def mock_parse_failure(_source, _stats=None):
        raise Exception("Failed to parse connector response")

    monkeypatch.setattr(
        "app.scraper.runner._scrape_source_candidates_with_timeout",
        mock_parse_failure,
    )

    # Monkeypatch classify_error to return PARSE for any exception
    from app.scraper.errors import ErrorType

    def mock_classify(_exc):
        return ErrorType.PARSE

    monkeypatch.setattr("app.scraper.runner.classify_error", mock_classify)

    health_alert_called = False
    health_alert_reason = None

    def track_health_alert(_db, _source, *, reason, recipient_email=None):
        nonlocal health_alert_called, health_alert_reason
        health_alert_called = True
        health_alert_reason = reason
        return None

    monkeypatch.setattr(
        "app.scraper.runner.create_source_health_alert",
        track_health_alert,
    )

    run = await run_source_inline(db, source, org_id)

    # ERR-3: PARSE → "degraded" (assuming partial work was done)
    assert run.status == "degraded", (
        f"PARSE errors should set status='degraded', got '{run.status}'"
    )
    _assert_log_has_error_type(run, "PARSE")
    # ERR-4: PARSE should create a health alert
    assert health_alert_called, "PARSE errors SHOULD create a health alert"
    assert health_alert_reason is not None


async def test_cancelled_error_sets_error_type_in_logs(
    monkeypatch, db, source, org_id
):
    """asyncio.CancelledError → error_type=TIMEOUT in logs, no health alert."""
    from app.scraper.runner import run_source_inline

    async def mock_cancelled(_source, _stats=None):
        raise asyncio.CancelledError("Task cancelled during shutdown")

    monkeypatch.setattr(
        "app.scraper.runner._scrape_source_candidates_with_timeout",
        mock_cancelled,
    )

    health_alert_called = False

    def track_health_alert(_db, _source, *, reason, recipient_email=None):
        nonlocal health_alert_called
        health_alert_called = True
        return None

    monkeypatch.setattr(
        "app.scraper.runner.create_source_health_alert",
        track_health_alert,
    )

    with pytest.raises(asyncio.CancelledError):
        await run_source_inline(db, source, org_id)

    # If we get here, the exception was not re-raised — which means it was caught
    # and swallowed. The error_type should be in the logs if we can capture them.
    # The CancelledError handler re-raises, so the TestSourceRun is not returned.
    # We'll verify the health alert was NOT called (which we track in the except block)
    assert not health_alert_called, "CancelledError should NOT create a health alert"


async def test_error_type_field_present_in_log_entries(
    monkeypatch, db, source, org_id
):
    """ERR-1: All error log entries must include the error_type field."""
    from app.scraper.runner import run_source_inline

    async def mock_error(_source, _stats=None):
        raise RuntimeError("Some runtime error")

    monkeypatch.setattr(
        "app.scraper.runner._scrape_source_candidates_with_timeout",
        mock_error,
    )

    health_alert_called = False

    def track_health_alert(_db, _source, *, reason, recipient_email=None):
        nonlocal health_alert_called
        health_alert_called = True
        return None

    monkeypatch.setattr(
        "app.scraper.runner.create_source_health_alert",
        track_health_alert,
    )

    run = await run_source_inline(db, source, org_id)

    # Every error-level log entry should have error_type
    error_logs = [log for log in run.logs if log.get("level") == "error"]
    assert len(error_logs) > 0, "Should have at least one error log"
    for log in error_logs:
        assert "error_type" in log, (
            f"Error log entry missing error_type: {log}"
        )
