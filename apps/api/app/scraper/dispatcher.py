"""Scraper dispatcher — dual dispatch: Arq queue or inline runner.

Phase 1: always delegated to runner.run_source_inline.
Phase 2 (PR2): checks settings.redis_url — if set, enqueues an Arq job;
               otherwise falls back to run_source_inline (inline fallback).

The dispatcher also guards against duplicate runs for the same source:
if a SourceRun with status='running' already exists, the call is skipped.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

# Arq is imported at module level so monkeypatching works in tests.
# In production, redis_url must be set in the environment for these
# imports to be exercised — otherwise the inline path is always taken.
from arq import create_pool  # noqa: E402
from arq.connections import RedisSettings  # noqa: E402

from app.core.config import get_settings
from app.models import Source, SourceRun
from app.scraper.runner import run_source_inline


async def run_source(
    db, source: Source, organization_id: str | None = None
) -> SourceRun | None:
    """Dispatch a source scrape.

    Checks for an existing running SourceRun before delegating.
    Returns None if a duplicate running run is found.

    If ``settings.redis_url`` is configured, a queued SourceRun is created
    and an Arq job is enqueued (fire-and-forget). Otherwise the scrape runs
    inline via ``run_source_inline``.
    """
    # Change C: skip auto-paused sources
    if getattr(source, "auto_paused", False):
        return None

    # Check for an existing running run for this source
    existing = db.scalar(
        select(SourceRun).where(
            SourceRun.source_id == source.id,
            SourceRun.status == "running",
        )
    )
    if existing:
        return None

    settings = get_settings()
    if settings.redis_url:
        return await _dispatch_via_arq(db, source, organization_id)

    return await run_source_inline(db, source, organization_id)


async def _dispatch_via_arq(
    db, source: Source, organization_id: str | None = None
) -> SourceRun:
    """Create a queued SourceRun and enqueue an Arq job.

    Returns the queued SourceRun immediately — the actual scrape runs
    in the worker process.
    """
    settings = get_settings()
    assert settings.redis_url is not None

    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    pool = await create_pool(redis_settings)

    job = await enqueue_job(
        pool,
        "run_scrape_job",
        source.id,
        organization_id or source.organization_id or "",
    )

    run = _create_queued_run(
        source_id=source.id,
        job_id=job.job_id,
        organization_id=organization_id or source.organization_id,
    )
    db.add(run)
    db.flush()
    return run


async def enqueue_job(pool, function: str, *args) -> object:
    """Enqueue an Arq job and return the job object.

    Extracted as a top-level function so tests can monkeypatch it
    without importing arq internals.
    """
    return await pool.enqueue_job(function, *args)


def _create_queued_run(
    source_id: str,
    job_id: str,
    organization_id: str | None = None,
) -> SourceRun:
    """Create a ``SourceRun`` with status='queued'.

    This run is created synchronously by the API process to give the
    caller an immediate reference. The worker will update its status
    when the job executes.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    return SourceRun(
        source_id=source_id,
        status="queued",
        started_at=now,
        logs=[
            {
                "level": "info",
                "message": "Job enqueued to Arq worker",
                "arq_job_id": job_id,
            }
        ],
    )
