"""Scraper dispatcher — inline-only dispatch.

Guards against duplicate runs for the same source:
if a SourceRun with status='running' already exists, the call is skipped.
"""
from __future__ import annotations

from sqlalchemy import select

from app.core.config import get_settings
from app.models import Source, SourceRun
from app.scraper.runner import run_source_inline


async def run_source(
    db, source: Source, organization_id: str | None = None
) -> SourceRun | None:
    """Dispatch a source scrape — runs inline.

    Checks for an existing running SourceRun before delegating.
    Returns None if a duplicate running run is found.
    """
    # skip auto-paused sources
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

    return await run_source_inline(db, source, organization_id)
