"""Idempotent per-org source seeding Celery task.

GAP-1 (dashboard-redesign): seed_default_sources was previously called
inline from POST /auth/register, blocking the request for 5+ seconds on
Render free tier. The fix is to enqueue this task from the API; the
register handler returns immediately and the worker fills in the source
set asynchronously.

Idempotency: seed_default_sources in apps/api/app/db/seed.py checks for
an existing Source by (organization_id, key) and either updates it in
place or adds a new one. Re-running this task produces the same DB state
with no duplicate-key errors.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select

from app.db.seed import seed_default_sources
from app.db.session import SessionLocal
from app.models import Organization
from worker.app import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(name="seed_default_sources_for_org")
def seed_default_sources_for_org(organization_id: str) -> dict[str, object]:
    """Seed the default source set for a freshly registered organization.

    The Celery task is the safe-to-retry counterpart of the previous
    inline call: it opens its own SessionLocal so the request-path session
    is not reused, fetches the Organization by id, and delegates to
    ``seed_default_sources`` from ``apps/api/app/db/seed.py``. If the org
    does not exist (e.g. a stale task from a deleted org), the task logs
    a warning and returns a ``skipped`` status instead of raising.

    Returns a dict so the worker can serialise the result to the
    result backend; the API consumer (``enqueue_seed_default_sources``)
    only needs the Celery task id, not the payload.
    """
    db = SessionLocal()
    try:
        organization = db.scalar(select(Organization).where(Organization.id == organization_id))
        if organization is None:
            logger.warning("seed_default_sources_org_not_found", org_id=organization_id)
            return {"status": "skipped", "reason": "org_not_found"}
        result = seed_default_sources(db, organization)
        db.commit()
        return {"status": "completed", **result}
    except Exception as exc:  # pragma: no cover - re-raised for Celery retry
        db.rollback()
        logger.exception("seed_default_sources_failed", org_id=organization_id, error=str(exc))
        raise
    finally:
        db.close()
