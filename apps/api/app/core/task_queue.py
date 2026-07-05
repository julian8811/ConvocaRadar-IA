"""Inline task execution — Celery/Redis have been removed.

ConvocaRadar runs on Render free tier where Celery and Redis are not
available. All scraping and background work executes inline within the
API process using asyncio loops (see ``_run_periodic_source_sweep`` in
``app.main``).

This module exists as a compatibility shim for import sites that
previously dispatched to Celery. Every function now unconditionally
runs the inline fallback path.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


def enqueue_seed_default_sources(organization_id: str) -> str | None:
    """Seed default sources inline (no Celery broker available).

    Returns the literal ``"inline"`` on success, ``None`` on failure.
    """
    from sqlalchemy import select

    from app.db.seed import seed_default_sources
    from app.db.session import SessionLocal
    from app.models import Organization

    db = SessionLocal()
    try:
        organization = db.scalar(select(Organization).where(Organization.id == organization_id))
        if organization is None:
            logger.warning("seed_inline_org_not_found", org_id=organization_id)
            return None
        result = seed_default_sources(db, organization)
        db.commit()
        logger.info("seed_sources_inline_completed", org_id=organization_id, **result)
        return "inline"
    except Exception as exc:
        db.rollback()
        logger.exception("seed_inline_failed", org_id=organization_id, error=str(exc))
        return None
    finally:
        db.close()

