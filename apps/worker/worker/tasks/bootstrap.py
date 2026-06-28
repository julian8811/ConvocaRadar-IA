"""GAP-1 (dashboard-redesign): seed_default_sources_for_org Celery task.

Replaces the inline ``seed_default_sources`` call in POST /auth/register
with an idempotent background task. ``seed_default_sources`` in
apps/api/app/db/seed.py uses check-then-update on (organization_id, key),
so re-runs produce the same DB state with no duplicate-key errors.
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

    Opens its own SessionLocal so the request-path session is not
    reused, fetches the Organization by id, and delegates to
    ``seed_default_sources``. Unknown org ids return ``skipped`` instead
    of raising (Celery would otherwise mark the task as failed and
    retry indefinitely).
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
