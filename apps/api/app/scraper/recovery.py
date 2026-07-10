"""Scraper recovery — stale run detection and cleanup.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.models import SourceRun


def mark_stale_runs_failed(db) -> int:
    """Mark SourceRun records as failed when they have been 'running'
    for more than 10 minutes.

    Returns the number of runs marked as failed.
    """
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=10)
    stmt = (
        update(SourceRun)
        .where(
            SourceRun.status == "running",
            SourceRun.started_at <= cutoff,
        )
        .values(
            status="failed",
            finished_at=datetime.now(UTC).replace(tzinfo=None),
            error_message="Stale run: exceeded 10-minute timeout",
        )
        .execution_options(synchronize_session="fetch")
    )
    result = db.execute(stmt)
    db.flush()
    return result.rowcount
