"""Tests for source resilience: auto-recovery, retry, graceful degradation."""

from __future__ import annotations

from unittest.mock import MagicMock


from app.models import Source
from app.scraper.dispatcher import run_source


def test_auto_paused_source_skipped():
    """A source with auto_paused=True and recent last_run should be skipped."""
    from datetime import UTC, datetime, timedelta
    source = MagicMock(spec=Source)
    source.auto_paused = True
    source.last_run_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
    source.key = "test"
    source.consecutive_empty_runs = 5
    source.selector_failures = 3
    db = MagicMock()
    db.scalar.return_value = None
    db.get_bind.return_value.dialect.name = "sqlite"
    import asyncio
    r = asyncio.run(run_source(db, source, organization_id="test-org"))
    assert r is None


def test_consecutive_empty_runs_increments():
    """When items_found == 0, consecutive_empty_runs should increment."""
    from app.services.scoring import update_consecutive_empty_runs
    assert update_consecutive_empty_runs(0, 0) == 1
    assert update_consecutive_empty_runs(0, 2) == 3


def test_consecutive_empty_runs_resets():
    """When items_found > 0, consecutive_empty_runs should reset to 0."""
    from app.services.scoring import update_consecutive_empty_runs
    assert update_consecutive_empty_runs(5, 3) == 0
    assert update_consecutive_empty_runs(1, 99) == 0


def test_auto_pause_triggered():
    """After 3 consecutive empty runs, should_auto_pause returns True."""
    from app.services.scoring import should_auto_pause
    assert should_auto_pause(3) is True
    assert should_auto_pause(5) is True


def test_auto_pause_not_triggered():
    """Below 3 consecutive empty runs, should not auto-pause."""
    from app.services.scoring import should_auto_pause
    assert should_auto_pause(0) is False
    assert should_auto_pause(2) is False
