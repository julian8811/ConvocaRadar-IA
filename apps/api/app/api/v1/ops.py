"""Operational endpoints.

Celery/Redis have been removed — all work runs inline within the API
process. The ``/ops/worker-health`` endpoint that probed the Celery
worker has been removed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(prefix="/ops", tags=["ops"])


@router.get("/health")
def health_check(db: Session = Depends(get_db)):
    from app.core.metrics import get_metrics

    metrics = get_metrics()
    return {"status": "ok", "faculty_match": metrics}
