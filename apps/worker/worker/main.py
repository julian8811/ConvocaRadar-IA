"""Arq WorkerSettings and scrape-job function for ConvocaRadar.

This module is loaded by ``arq`` when the worker starts:

    python -m arq worker.main.WorkerSettings

The worker shares the same database and scraper modules as the API
(``convocaradar-api`` is installed as an editable dependency).
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from arq.connections import RedisSettings
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.models import Source, SourceRun


# ---------------------------------------------------------------------------
# Arq WorkerSettings — arq scans this class for its configuration
# ---------------------------------------------------------------------------


class WorkerSettings:
    """Arq worker configuration.

    Attributes:
        functions: List of async functions arq can dispatch.
        on_startup: Called once when the worker starts.
        max_jobs: Max concurrent jobs per worker.
        job_timeout: Max seconds a job can run before being cancelled.
        keep_result: Seconds to keep job results in Redis.
        redis_settings: Inferred from ``REDIS_URL``.
    """

    functions: list = ["worker.main.run_scrape_job"]
    on_startup: str = "worker.main.startup"
    max_jobs: int = 4
    job_timeout: int = 180
    keep_result: int = 3600

    @property
    def redis_settings(self) -> RedisSettings:
        settings = get_settings()
        assert settings.redis_url is not None, "REDIS_URL is not configured"
        return RedisSettings.from_dsn(settings.redis_url)


# ---------------------------------------------------------------------------
# Startup hook
# ---------------------------------------------------------------------------


async def startup(ctx: dict) -> None:
    """Worker startup — mark any stale runs as failed and log readiness."""
    settings = get_settings()
    engine = create_engine(settings.database_url)
    session_maker = sessionmaker(bind=engine)

    with session_maker() as db:
        from app.scraper.recovery import mark_stale_runs_failed

        count = mark_stale_runs_failed(db)
        db.commit()

    ctx["engine"] = engine
    ctx["session_maker"] = session_maker


# ---------------------------------------------------------------------------
# Job function
# ---------------------------------------------------------------------------


async def run_scrape_job(
    ctx: dict,
    source_id: str,
    organization_id: str,
) -> dict:
    """Arq job: scrape a single source and persist opportunities.

    Called by the Arq worker when the dispatcher enqueues a job.
    Uses the inline runner to perform the actual scrape.

    Args:
        ctx: Arq worker context (contains session_maker).
        source_id: The Source.id to scrape.
        organization_id: The Organization.id that owns this source.

    Returns:
        A dict with summary stats from the scrape run.
    """
    session_maker: sessionmaker = ctx["session_maker"]
    db: Session = session_maker()

    try:
        source = db.query(Source).filter(Source.id == source_id).first()
        if not source:
            _update_run_status(db, source_id, "failed", "Source not found")
            return {"status": "failed", "error": "Source not found"}

        from app.scraper.runner import run_source_inline

        run = await run_source_inline(db, source, organization_id)
        db.commit()

        return {
            "status": run.status,
            "run_id": run.id,
            "items_found": run.items_found,
            "items_created": run.items_created,
            "items_updated": run.items_updated,
        }
    except asyncio.CancelledError:
        db.rollback()
        _update_run_status(db, source_id, "failed", "Job cancelled (shutdown/timeout)")
        return {"status": "failed", "error": "Cancelled"}
    except Exception as exc:
        db.rollback()
        _update_run_status(db, source_id, "failed", str(exc))
        return {"status": "failed", "error": str(exc)}
    finally:
        db.close()


def _update_run_status(
    db: Session,
    source_id: str,
    status: str,
    error_message: str | None = None,
) -> None:
    """Find the most recent queued/running run for this source and mark it."""
    run = (
        db.query(SourceRun)
        .filter(
            SourceRun.source_id == source_id,
            SourceRun.status.in_(["queued", "running"]),
        )
        .order_by(SourceRun.created_at.desc())
        .first()
    )
    if run:
        run.status = status
        run.finished_at = datetime.now(UTC).replace(tzinfo=None)
        if error_message:
            run.error_message = error_message
        db.commit()
