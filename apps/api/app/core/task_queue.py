from __future__ import annotations

from typing import Any
import ssl

import structlog

from app.core.config import get_settings

logger = structlog.get_logger(__name__)


def _redis_ssl_options(redis_url: str) -> dict[str, object]:
    if not redis_url.startswith("rediss://"):
        return {}
    return {"ssl_cert_reqs": ssl.CERT_NONE}


def enqueue_scrape_source(
    source_key: str,
    base_url: str,
    source_type: str | None = None,
    *,
    source_run_id: str,
    task_id: str,
    countdown_seconds: int | None = None,
) -> str | None:
    settings = get_settings()
    execution_mode = settings.scraping_execution_mode.lower().strip()
    if execution_mode not in {"inline", "worker", "auto"}:
        logger.warning("invalid_scraping_execution_mode_using_inline", mode=settings.scraping_execution_mode)
        execution_mode = "inline"
    if execution_mode == "inline" or (execution_mode == "auto" and not settings.use_worker):
        return None
    try:
        from celery import Celery
    except ImportError as exc:
        logger.warning("celery_not_available_for_scraping", error=str(exc))
        return None

    try:
        ssl_options = _redis_ssl_options(settings.redis_url)
        celery_app = Celery("convocaradar-api-producer", broker=settings.redis_url, backend=settings.redis_url)
        if ssl_options:
            celery_app.conf.update(broker_use_ssl=ssl_options, redis_backend_use_ssl=ssl_options)
        result = celery_app.send_task(
            "scrape_source",
            kwargs={
                "source_key": source_key,
                "base_url": base_url,
                "source_type": source_type,
                "source_run_id": source_run_id,
                "task_id": task_id,
            },
            countdown=countdown_seconds,
        )
        return str(result.id)
    except Exception as exc:
        logger.warning("scrape_enqueue_failed_falling_back_to_local", source_key=source_key, error=str(exc))
        return None


def enqueue_seed_default_sources(organization_id: str) -> str | None:
    """Dispatch seed_default_sources_for_org to Celery.

    GAP-1 (dashboard-redesign): this helper is called from POST /auth/register
    after the new user + organization are committed. It must never block the
    request path; on any failure (broker down, network error, missing celery)
    it logs a warning and returns ``None``. The bootstrap.py startup sweep
    in apps/api/app/db/bootstrap.py covers cold-orgs as a safety net.

    Returns the Celery task id on success, or ``None`` on any failure.
    """
    settings = get_settings()
    try:
        from celery import Celery
    except ImportError as exc:
        logger.warning("celery_not_available_for_seed_sources", org_id=organization_id, error=str(exc))
        return None

    try:
        ssl_options = _redis_ssl_options(settings.redis_url)
        celery_app = Celery(
            "convocaradar-api-producer",
            broker=settings.redis_url,
            backend=settings.redis_url,
        )
        if ssl_options:
            celery_app.conf.update(broker_use_ssl=ssl_options, redis_backend_use_ssl=ssl_options)
        result = celery_app.send_task(
            "seed_default_sources_for_org",
            kwargs={"organization_id": organization_id},
        )
        return str(result.id)
    except Exception as exc:
        logger.warning("seed_sources_enqueue_failed", org_id=organization_id, error=str(exc))
        return None


def task_payload(**kwargs: Any) -> dict[str, Any]:
    return {key: value for key, value in kwargs.items() if value is not None}
