"""Tests for the app.scraper module (PR 1 - Worker Separation).

TDD Cycle: tests written FIRST, then implementation.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_convocaradar.db")

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.db.seed import seed  # noqa: E402
from app.models import Organization, Source, SourceRun  # noqa: E402


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _seed():
    """Seed the test DB once per module."""
    seed()


@pytest.fixture
def db(_seed):
    """Provide a clean DB session per test with SourceRuns cleared."""
    from app.models import SourceRun

    session = SessionLocal()
    # Clear any SourceRuns left by previous tests so assertions about
    # "no existing running run" are deterministic.
    session.query(SourceRun).delete()
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def source(db) -> Source:
    """Return a seeded source for testing."""
    src = db.scalar(select(Source).where(Source.key == "minciencias"))
    assert src is not None, "seeded source 'minciencias' not found"
    return src


@pytest.fixture
def org_id(db) -> str:
    """Return the seeded org ID."""
    org = db.scalar(
        select(Organization).where(Organization.slug == "convocaradar-local")
    )
    assert org is not None, "seeded org not found"
    return str(org.id)


# ---------------------------------------------------------------------------
# Test 3.1: run_source_inline returns success SourceRun with correct counts
# ---------------------------------------------------------------------------


async def test_run_source_inline_returns_success_run(monkeypatch, db, source, org_id):
    """run_source_inline should return a SourceRun with status='success'
    and items_found/items_created matching the mocked opportunities."""
    from app.scraper.runner import run_source_inline

    opportunities_created: list = []

    async def mock_scrape_candidates(_source, _stats=None):
        from app.schemas import OpportunityCreate

        return [
            OpportunityCreate(
                source_id=_source.id,
                external_id="tdd-test-001",
                title="TDD Test Opportunity 1",
                entity="Test Entity",
                country="Colombia",
                summary="Test summary",
                raw_text="Test raw text",
                confidence_score=0.8,
            ),
            OpportunityCreate(
                source_id=_source.id,
                external_id="tdd-test-002",
                title="TDD Test Opportunity 2",
                entity="Test Entity",
                country="Colombia",
                summary="Test summary 2",
                raw_text="Test raw text 2",
                confidence_score=0.9,
            ),
        ]

    def mock_create_opportunity(_db, data, organization_id=None):
        """Mock that creates an in-memory Opportunity-like object."""
        from app.models import Opportunity

        now = datetime.now(UTC).replace(tzinfo=None)
        opp = Opportunity(
            id=f"tdd-opp-{len(opportunities_created) + 1}",
            source_id=data.source_id or source.id,
            external_id=data.external_id,
            title=data.title,
            entity=data.entity,
            country=data.country,
            slug=data.title.lower().replace(" ", "-"),
            summary=data.summary or "",
            raw_text=data.raw_text or "",
            confidence_score=data.confidence_score or 0.5,
            first_seen_at=now,
            last_seen_at=now,
        )
        opportunities_created.append(opp)
        return opp

    monkeypatch.setattr(
        "app.scraper.runner._scrape_candidates", mock_scrape_candidates
    )
    monkeypatch.setattr(
        "app.scraper.runner.create_opportunity", mock_create_opportunity
    )

    run = await run_source_inline(db, source, org_id)

    assert run.status == "success"
    assert run.items_found == 2
    assert run.items_created == 2
    assert run.items_updated == 0
    assert run.items_failed == 0
    assert run.finished_at is not None
    assert run.source_id == source.id
    assert len(opportunities_created) == 2


# ---------------------------------------------------------------------------
# Test 3.2: run_source_inline returns failed SourceRun on TimeoutError
# ---------------------------------------------------------------------------


async def test_run_source_inline_returns_failed_run_on_timeout(
    monkeypatch, db, source, org_id
):
    """When _scrape_source_candidates_with_timeout raises TimeoutError,
    run_source_inline must return a SourceRun with status='failed'."""
    from app.scraper.runner import run_source_inline

    async def mock_timeout(_source, _stats=None):
        raise TimeoutError("Simulated timeout for TDD test")

    monkeypatch.setattr(
        "app.scraper.runner._scrape_source_candidates_with_timeout",
        mock_timeout,
    )

    run = await run_source_inline(db, source, org_id)

    assert run.status == "failed"
    assert run.finished_at is not None
    assert run.error_message is not None
    assert "timeout" in run.error_message.lower()


# ---------------------------------------------------------------------------
# Test 3.3: run_source skips duplicate when source already has a running run
# ---------------------------------------------------------------------------


async def test_run_source_skips_when_source_already_running(
    monkeypatch, db, source, org_id
):
    """run_source should return None (skip) when the source already has
    a SourceRun with status='running'."""
    from app.scraper.dispatcher import run_source

    # Create a pre-existing "running" SourceRun
    now = datetime.now(UTC).replace(tzinfo=None)
    existing = SourceRun(
        source_id=source.id,
        status="running",
        started_at=now,
        logs=[{"level": "info", "message": "Pre-existing run"}],
    )
    db.add(existing)
    db.flush()

    # Even if we make _scrape_candidates noisy, it should never be called
    call_count = 0

    async def never_called(_source, _stats=None):
        nonlocal call_count
        call_count += 1
        return []

    monkeypatch.setattr("app.scraper.runner._scrape_candidates", never_called)

    result = await run_source(db, source, org_id)

    assert result is None, "Expected None when skipping duplicate running run"
    assert call_count == 0, "_scrape_candidates should NOT be called"
    # Original SourceRun should still be running
    db.refresh(existing)
    assert existing.status == "running"


# ---------------------------------------------------------------------------
# Test 3.4: recovery.mark_stale_runs_failed marks old running runs as failed
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Test 3.1 TRIANGULATION: run_source_inline with 0 opportunities → "degraded"
# ---------------------------------------------------------------------------


async def test_run_source_inline_returns_degraded_when_no_opportunities(
    monkeypatch, db, source, org_id
):
    """When _scrape_candidates returns 0 valid opportunities,
    run_source_inline must return a SourceRun with status='degraded'."""
    from app.scraper.runner import run_source_inline

    async def mock_scrape_empty(_source, _stats=None):
        return []

    def mock_create_opportunity_never_called(_db, data, organization_id=None):
        raise AssertionError("create_opportunity should NOT be called with 0 candidates")

    monkeypatch.setattr(
        "app.scraper.runner._scrape_candidates", mock_scrape_empty
    )
    monkeypatch.setattr(
        "app.scraper.runner.create_opportunity", mock_create_opportunity_never_called
    )

    run = await run_source_inline(db, source, org_id)

    assert run.status == "degraded"
    assert run.items_found == 0
    assert run.items_created == 0
    assert run.items_updated == 0
    assert run.items_failed == 0


# ---------------------------------------------------------------------------
# Test 3.2 TRIANGULATION: run_source_inline with generic Exception
# ---------------------------------------------------------------------------


async def test_run_source_inline_returns_failed_on_generic_error(
    monkeypatch, db, source, org_id
):
    """Any Exception (not just TimeoutError) should result in a failed run."""
    from app.scraper.runner import run_source_inline

    async def mock_error(_source, _stats=None):
        raise RuntimeError("Simulated runtime error for TDD test")

    monkeypatch.setattr(
        "app.scraper.runner._scrape_source_candidates_with_timeout",
        mock_error,
    )

    run = await run_source_inline(db, source, org_id)

    assert run.status == "failed"
    assert run.error_message is not None
    assert "runtime error" in run.error_message.lower()


# ---------------------------------------------------------------------------
# Test 3.3 TRIANGULATION: run_source delegates to run_source_inline when no
# existing running run
# ---------------------------------------------------------------------------


async def test_run_source_delegates_when_no_existing_run(
    monkeypatch, db, source, org_id
):
    """When no existing running SourceRun exists, run_source should
    delegate to run_source_inline and return the resulting run."""
    from app.scraper.dispatcher import run_source

    calls = []

    async def tracking_inline(_db, _source, _org_id):
        calls.append((_source.key, _org_id))
        run = SourceRun(
            source_id=_source.id,
            status="success",
            started_at=datetime.now(UTC).replace(tzinfo=None),
            finished_at=datetime.now(UTC).replace(tzinfo=None),
            items_found=0,
        )
        return run

    monkeypatch.setattr(
        "app.scraper.dispatcher.run_source_inline", tracking_inline
    )

    result = await run_source(db, source, org_id)

    assert result is not None
    assert result.status == "success"
    assert len(calls) == 1
    assert calls[0][0] == source.key


# ---------------------------------------------------------------------------
# Test 3.4: recovery.mark_stale_runs_failed marks old running runs as failed
# ---------------------------------------------------------------------------


async def test_mark_stale_runs_failed_marks_old_running_runs(db):
    """mark_stale_runs_failed should set status='failed' for runs with
    status='running' and started_at older than 10 minutes."""
    from app.scraper.recovery import mark_stale_runs_failed

    now = datetime.now(UTC).replace(tzinfo=None)

    # Create a stale run (20 min ago - should be marked)
    stale = SourceRun(
        source_id="stale-source",
        status="running",
        started_at=now - timedelta(minutes=20),
        logs=[],
    )
    db.add(stale)
    db.flush()

    # Create a recent run (5 min ago - should NOT be marked)
    recent = SourceRun(
        source_id="recent-source",
        status="running",
        started_at=now - timedelta(minutes=5),
        logs=[],
    )
    db.add(recent)
    db.flush()

    # Create a non-running stale run (should NOT be marked)
    failed = SourceRun(
        source_id="failed-source",
        status="failed",
        started_at=now - timedelta(minutes=20),
        finished_at=now - timedelta(minutes=18),
        error_message="already failed",
        logs=[],
    )
    db.add(failed)
    db.flush()

    marked = mark_stale_runs_failed(db)

    # Stale running run should be marked failed
    db.refresh(stale)
    assert stale.status == "failed"
    assert stale.finished_at is not None

    # Recent run should still be running
    db.refresh(recent)
    assert recent.status == "running"

    # Already-failed run should stay failed
    db.refresh(failed)
    assert failed.status == "failed"

    assert marked >= 1


# ---------------------------------------------------------------------------
# Test 3.4 TRIANGULATION: boundary cases for stale run detection
# ---------------------------------------------------------------------------


async def test_mark_stale_runs_failed_boundary(db):
    """mark_stale_runs_failed must NOT mark runs started less than 10 min ago,
    and MUST mark runs started more than 10 min ago, but leave non-running
    runs alone even when started long ago."""
    from app.scraper.recovery import mark_stale_runs_failed

    now = datetime.now(UTC).replace(tzinfo=None)

    # Run at exactly 9 min 59 sec (should NOT be marked)
    almost_recent = SourceRun(
        source_id="almost-recent-source",
        status="running",
        started_at=now - timedelta(minutes=9, seconds=59),
        logs=[],
    )
    db.add(almost_recent)
    db.flush()

    # Run at exactly 10 min 1 sec (should be marked)
    just_stale = SourceRun(
        source_id="just-stale-source",
        status="running",
        started_at=now - timedelta(minutes=10, seconds=1),
        logs=[],
    )
    db.add(just_stale)
    db.flush()

    # Run at exactly 10 minutes — less than 10 min (< 10 min means strictly less)
    exactly_10 = SourceRun(
        source_id="exactly-10-source",
        status="running",
        started_at=now - timedelta(minutes=10),
        logs=[],
    )
    db.add(exactly_10)
    db.flush()

    marked = mark_stale_runs_failed(db)

    # 9 min 59 sec should still be running
    db.refresh(almost_recent)
    assert almost_recent.status == "running"

    # 10 min 1 sec should be failed
    db.refresh(just_stale)
    assert just_stale.status == "failed"

    # Exactly 10 min — cutoff is <=, so exactly 10 min IS marked
    db.refresh(exactly_10)
    assert exactly_10.status == "failed"

    assert marked == 2  # just_stale + exactly_10 were marked
