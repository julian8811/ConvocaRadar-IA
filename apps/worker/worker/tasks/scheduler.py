import httpx

from worker.app import celery_app
from worker.config import get_settings


def _post_internal(path: str) -> dict[str, object]:
    settings = get_settings()
    url = f"{settings.backend_url.rstrip('/')}/api/v1/internal/{path.lstrip('/')}"
    response = httpx.post(url, headers={"X-Internal-API-Key": settings.internal_api_key}, timeout=60)
    response.raise_for_status()
    return response.json()


@celery_app.task(name="run_enabled_sources")
def run_enabled_sources() -> dict[str, object]:
    return _post_internal("/scheduler/sources/run-enabled")


@celery_app.task(name="send_due_alerts")
def send_due_alerts() -> dict[str, object]:
    return _post_internal("/scheduler/alerts/send-due")
