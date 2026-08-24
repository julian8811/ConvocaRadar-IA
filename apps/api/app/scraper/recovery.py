"""Scraper recovery — stale run detection and cleanup."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.models import SourceRun, Task


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
    db.execute(
        update(Task)
        .where(
            Task.status.in_(("queued", "running")),
            Task.created_at <= cutoff,
            Task.task_type.in_(("source_sweep", "source_scrape")),
        )
        .values(
            status="failed",
            finished_at=datetime.now(UTC).replace(tzinfo=None),
            error_message="Stale task: execution interrupted or timed out",
        )
        .execution_options(synchronize_session=False)
    )
    db.flush()
    return result.rowcount
