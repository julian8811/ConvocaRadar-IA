"""Scraper dispatcher — currently delegates to inline runner.

Phase 1: always delegates to runner.run_source_inline (no Redis check yet).
Phase 2+ will add queue-based dispatch.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.models import Source, SourceRun

from app.scraper.runner import run_source_inline


async def run_source(
    db, source: Source, organization_id: str | None = None
) -> SourceRun | None:
    """Dispatch a source scrape.

    Checks for an existing running SourceRun before delegating.
    Returns None if a duplicate running run is found.
    """
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
