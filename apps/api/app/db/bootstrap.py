from __future__ import annotations

import logging
import threading

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.seed import seed
from app.db.session import SessionLocal
from app.models import Opportunity, Source
from app.services import execute_source_run_locally

logger = logging.getLogger(__name__)

DEFAULT_BOOTSTRAP_SOURCE_KEYS = (
    "grants-gov-rss",
    "grants-gov",
    "innpulsa",
    "minciencias",
    "nsf-funding-rss",
)


def bootstrap_priority_sources(*, blocking: bool = False) -> dict[str, int | str] | None:
    settings = get_settings()
    if not settings.bootstrap_sources_on_startup:
        return None

    db = SessionLocal()
    try:
        opportunity_total = db.scalar(select(func.count()).select_from(Opportunity)) or 0
        if opportunity_total > 0:
            return {"status": "skipped", "reason": "opportunities_already_present", "opportunities": opportunity_total}

        keys = settings.bootstrap_source_key_list or list(DEFAULT_BOOTSTRAP_SOURCE_KEYS)
        sources = list(
            db.scalars(
                select(Source).where(
                    Source.enabled.is_(True),
                    Source.key.in_(keys),
                )
            )
        )
        if not sources:
            return {"status": "skipped", "reason": "no_matching_sources", "sources_attempted": 0}

        runs_started = 0
        items_created = 0
        for source in sources:
            run = execute_source_run_locally(db, source, organization_id=source.organization_id)
            runs_started += 1
            items_created += run.items_created or 0
            db.commit()

        return {
            "status": "completed",
            "sources_attempted": runs_started,
            "items_created": items_created,
        }
    except Exception:
        db.rollback()
        logger.exception("Bootstrap scrape failed")
        raise
    finally:
        db.close()


def _bootstrap_worker() -> None:
    try:
        result = bootstrap_priority_sources(blocking=True)
        if result:
            logger.info("Bootstrap scrape finished: %s", result)
    except Exception:
        logger.exception("Background bootstrap scrape failed")


def ensure_bootstrap_data() -> None:
    seed()
    settings = get_settings()
    if not settings.bootstrap_sources_on_startup:
        return

    db = SessionLocal()
    try:
        opportunity_total = db.scalar(select(func.count()).select_from(Opportunity)) or 0
    finally:
        db.close()

    if opportunity_total > 0:
        return

    if settings.bootstrap_sources_blocking:
        bootstrap_priority_sources(blocking=True)
        return

    thread = threading.Thread(target=_bootstrap_worker, name="convocaradar-bootstrap", daemon=True)
    thread.start()
