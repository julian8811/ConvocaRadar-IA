"""Operational endpoints.

Celery/Redis have been removed — all work runs inline within the API
process. The ``/ops/worker-health`` endpoint is kept as a stub that
returns the API's own health, since there is no separate worker process
to query.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.models import User

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/ops", tags=["ops"])


def _require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user


@router.get("/worker-health")
def worker_health(endpoint: User = Depends(_require_admin)) -> dict[str, str]:
    """Inline-only worker health.

    ConvocaRadar no longer runs a separate Celery worker. All scraping
    and background work executes inline within the API process. This
    endpoint returns the API's own health as a proxy.
    """
    return {
        "status": "ok",
        "mode": "inline",
        "message": "All tasks run inline within the API process. No separate worker.",
    }
