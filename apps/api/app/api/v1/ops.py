"""PR6: operational endpoints.

Currently a single endpoint — ``GET /api/v1/ops/worker-health`` — that
dispatches the ``worker_health`` Celery task and waits up to 5 seconds
for a reply. Used by operators (and any future monitoring integration)
to confirm the worker process is alive and consuming tasks separately
from the API.

The endpoint is admin-only because the worker hostname and timestamp
leak small bits of deployment topology (which Render container is
running, when it last picked up a task). A non-admin caller has no
legitimate need to see that.
"""

from __future__ import annotations

import ssl

import structlog
from celery import Celery
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.core.config import Settings, get_settings
from app.models import User

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/ops", tags=["ops"])

settings: Settings = get_settings()

# A module-level Celery producer so the tests can monkeypatch ``send_task``
# on it. The worker module's ``worker.app.celery_app`` has the same broker
# URL by construction; we create a separate lightweight client here so the
# API process does not need to import worker.app (which would force the
# worker package onto the API image).
_celery_app = Celery(
    "convocaradar-api-ops-producer",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
if settings.redis_url.startswith("rediss://"):
    _celery_app.conf.update(
        broker_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE},
        redis_backend_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE},
    )

WORKER_HEALTH_TIMEOUT_SECONDS = 5


def _require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user


@router.get("/worker-health")
def worker_health(_: User = Depends(_require_admin)) -> dict[str, str]:
    """Dispatch ``worker_health`` and return the worker's reply.

    * **200** with the worker's JSON payload on success.
    * **504** if the worker does not reply within 5 seconds.
    * **503** if the API is configured to run inline (``USE_WORKER=false``).
    * **401/403** for unauthenticated or non-admin callers (handled by
      the ``_require_admin`` dependency).
    """
    if not settings.use_worker:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Worker is not enabled (USE_WORKER=false)",
        )

    try:
        async_result = _celery_app.send_task("worker_health")
    except Exception as exc:  # noqa: BLE001 - broker may be down
        logger.warning("worker_health_enqueue_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cannot reach worker broker",
        ) from exc

    try:
        payload = async_result.get(timeout=WORKER_HEALTH_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        logger.warning("worker_health_timeout", timeout=WORKER_HEALTH_TIMEOUT_SECONDS)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=(
                f"Timeout: worker did not respond within "
                f"{WORKER_HEALTH_TIMEOUT_SECONDS}s"
            ),
        ) from exc

    if not isinstance(payload, dict):
        # The task is supposed to return a dict; if the worker replied with
        # anything else, surface a 502 so the operator can investigate
        # without us hiding the mis-shape behind a 200.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Worker returned unexpected payload type: {type(payload).__name__}",
        )
    return payload
