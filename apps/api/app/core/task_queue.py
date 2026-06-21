from __future__ import annotations

from typing import Any

from app.core.config import get_settings


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
    if not settings.use_worker:
        return None
    try:
        from celery import Celery
    except ImportError:
        return None

    celery_app = Celery("convocaradar-api-producer", broker=settings.redis_url, backend=settings.redis_url)
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


def task_payload(**kwargs: Any) -> dict[str, Any]:
    return {key: value for key, value in kwargs.items() if value is not None}
