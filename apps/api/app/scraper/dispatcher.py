"""Scraper dispatcher — inline-only dispatch.

Guards against duplicate runs for the same source:
if a SourceRun with status='running' already exists, the call is skipped.
Also handles auto-recovery for paused sources after a cooldown period.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, text

from app.models import Source, SourceRun
from app.scraper.runner import run_source_inline

# Number of hours an auto-paused source must wait before it can be
# automatically re-activated and tried again.
_AUTO_PAUSE_COOLDOWN_HOURS = 24


def _cooldown_elapsed(source: Source) -> bool:
    """Pure check: has the auto-pause cooldown elapsed for this source?"""
    last_run = getattr(source, "last_run_at", None)
    if last_run is None:
        return False
    elapsed = (datetime.now(UTC).replace(tzinfo=None) - last_run).total_seconds()
    return elapsed >= _AUTO_PAUSE_COOLDOWN_HOURS * 3600


def dispatch_block_reason(db, source: Source) -> dict[str, object] | None:
    """Read-only mirror of ``run_source``'s skip decisions (no side effects).

    Returns ``{"reason": "paused_cooldown", ...}`` when the source is
    auto-paused inside its 24h cooldown (or paused with no run history),
    ``{"reason": "already_running", "run_id": ...}`` when a SourceRun is
    already in progress, else ``None``.

    Unlike ``run_source`` this never reactivates: a source whose cooldown
    already elapsed is NOT blocked (``None``) — reactivation stays inside
    ``run_source`` so HTTP guards using this helper cannot mutate pause
    state. Parity with ``run_source`` is pinned by
    tests/test_source_run_conflict.py.
    """
    if getattr(source, "auto_paused", False):
        last_run = getattr(source, "last_run_at", None)
        if last_run is None:
            return {"reason": "paused_cooldown"}
        elapsed = (datetime.now(UTC).replace(tzinfo=None) - last_run).total_seconds()
        cooldown_seconds = _AUTO_PAUSE_COOLDOWN_HOURS * 3600
        if elapsed < cooldown_seconds:
            return {
                "reason": "paused_cooldown",
                "retry_after_seconds": int(cooldown_seconds - elapsed),
            }
        return None
    existing = db.scalar(
        select(SourceRun).where(
            SourceRun.source_id == source.id,
            SourceRun.status == "running",
        )
    )
    if existing is not None:
        return {"reason": "already_running", "run_id": str(existing.id)}
    return None


async def run_source(db, source: Source, organization_id: str | None = None) -> SourceRun | None:
    """Dispatch a source scrape — runs inline.

    Checks for an existing running SourceRun before delegating.
    Returns None if a duplicate running run is found.

    Auto-paused sources are reactivated after ``_AUTO_PAUSE_COOLDOWN_HOURS``
    hours since their last attempt, preventing permanent silencing.
    """
    # Auto-recovery: re-activate paused sources after cooldown
    if getattr(source, "auto_paused", False):
        last_run = source.last_run_at
        if last_run is not None:
            elapsed = (datetime.now(UTC).replace(tzinfo=None) - last_run).total_seconds()
            if elapsed >= _AUTO_PAUSE_COOLDOWN_HOURS * 3600:
                source.auto_paused = False
                source.consecutive_empty_runs = 0
                source.selector_failures = 0
                import structlog

                structlog.get_logger(__name__).info(
                    "source_auto_reactivated",
                    source_key=source.key,
                    cooldown_hours=_AUTO_PAUSE_COOLDOWN_HOURS,
                )
            else:
                return None
        else:
            # Never run before — skip (paused for a reason, no history)
            return None

    # PostgreSQL transaction advisory locks prevent the periodic scheduler
    # and a user-triggered sweep from scraping the same source concurrently.
    if db.get_bind().dialect.name == "postgresql":
        acquired = db.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtext(:source_id))"),
            {"source_id": str(source.id)},
        )
        if not acquired:
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

    return await run_source_inline(db, source, organization_id)
