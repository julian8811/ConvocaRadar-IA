"""Connector factory and scraping execution functions.

Extracted from ``_legacy.py`` (PR C-1). Provides the connector dispatch
function, scraping frequency checks, and async scraping execution with
timeout support.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Source
from app.schemas import OpportunityCreate


def connector_for(
    source_key: str,
    base_url: str | None = None,
    source_type: str | None = None,
    *,
    entity_name: str | None = None,
    default_country: str | None = None,
    default_categories: list[str] | None = None,
    connector_config: dict | None = None,
):
    from app.connectors.factory import connector_for as worker_connector_for

    return worker_connector_for(
        source_key,
        base_url,
        source_type,
        entity_name=entity_name,
        default_country=default_country,
        default_categories=default_categories,
        connector_config=connector_config,
    )


SLOW_SCRAPE_SOURCE_KEYS = frozenset(
    {
        "innovamos-global-innovation-fund",
        "innovamos-fid",
        "eu-funding-tenders",
        "minciencias",
        "ukri-opportunities",
        "horizon-europe-sedia",
        "eic-accelerator",
        "procolombia-convocatorias",
        # PR5 follow-up: apc-colombia's HTML page is heavy enough to timeout
        # under Render free's 30-90s scraping window. Regression test
        # apps/api/tests/test_sources.py::test_apc_colombia_is_classified_as_slow_source
        # pins this entry.
        "apc-colombia",
    }
)
SLOW_SCRAPE_SOURCE_TYPES = frozenset({"hybrid"})


def is_slow_scrape_source(source: Source) -> bool:
    return (
        source.key in SLOW_SCRAPE_SOURCE_KEYS
        or (source.source_type or "") in SLOW_SCRAPE_SOURCE_TYPES
    )


def _jitter_for_source(source: Source) -> timedelta:
    """Deterministic jitter 0-599s based on source.id hash — avoids thundering herd."""
    import hashlib

    h = int(hashlib.sha256((source.id or "0").encode()).hexdigest()[:8], 16)
    return timedelta(seconds=h % 600)


def source_due_for_scraping(source: Source, *, now: datetime | None = None) -> bool:
    current = now or datetime.now(UTC).replace(tzinfo=None)
    frequency = (source.scraping_frequency or "daily").lower()
    if frequency in {"hourly", "every_hour", "daily", "every_day"}:
        # Daily/hourly always due — health-aware backoff only if heavily failing
        fails = int(getattr(source, "consecutive_empty_runs", 0) or 0)
        if fails >= 5 and source.last_run_at:
            # Back off heavily failing daily: require at least 6h since last run
            elapsed = current - source.last_run_at
            backoff = timedelta(hours=min(24, 4 * fails))
            jitter = _jitter_for_source(source)
            return elapsed >= backoff + jitter
        return True
    if not source.last_run_at:
        return True
    elapsed = current - source.last_run_at
    jitter = _jitter_for_source(source)
    fails = int(getattr(source, "consecutive_empty_runs", 0) or 0)
    backoff = timedelta(0)
    if fails:
        # Up to 24h extra backoff, 6h per failure
        backoff = timedelta(hours=min(24, fails * 6))
    if frequency in {"weekly", "every_week"}:
        return elapsed >= timedelta(days=7) + backoff + jitter
    if frequency in {"monthly", "every_month"}:
        return elapsed >= timedelta(days=28) + backoff + jitter
    return elapsed >= timedelta(days=1) + backoff + jitter


async def _scrape_source_candidates(
    source: Source, stats: dict[str, object] | None = None
) -> list[OpportunityCreate]:
    """Compatibility wrapper — the live scrape path is ``app.scraper.runner``."""
    from app.scraper.runner import _scrape_candidates

    return await _scrape_candidates(source, stats)


async def _scrape_source_candidates_with_timeout(
    source: Source, stats: dict[str, object] | None = None
) -> list[OpportunityCreate]:
    settings = get_settings()
    timeout_seconds = max(settings.scraping_max_source_seconds, 30)
    timeout_seconds = min(timeout_seconds, int(settings.per_connector_timeout_seconds))
    try:
        return await asyncio.wait_for(
            _scrape_source_candidates(source, stats), timeout=timeout_seconds
        )
    except TimeoutError as exc:
        raise TimeoutError(f"Scrape for source {source.key} exceeded {timeout_seconds}s") from exc


def execute_source_run_locally(
    db: Session, source: Source, organization_id: str | None = None
) -> object:
    """Thin sync wrapper — delegates to app.scraper.runner.run_source_inline.

    FastAPI sync endpoints run in a thread pool.  ``asyncio.run()`` in a
    thread can deadlock with the parent event loop on some platforms, so
    we use an explicit fresh loop (same pattern as the original).
    """
    from app.scraper.runner import run_source_inline

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(run_source_inline(db, source, organization_id))
    finally:
        loop.close()
