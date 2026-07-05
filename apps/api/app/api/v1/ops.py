"""Operational endpoints.

Celery/Redis have been removed — all work runs inline within the API
process. The ``/ops/worker-health`` endpoint that probed the Celery
worker has been removed.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/ops", tags=["ops"])
