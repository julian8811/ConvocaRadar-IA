"""PR6: minimal liveness task dispatched by ``GET /api/v1/ops/worker-health``.

The task returns a small JSON payload with the worker hostname and the
current UTC timestamp. It does NOT touch the database, the file system,
or any external service — the goal is to prove the Celery wire (broker +
result backend) is functional from the API's perspective. The keep-alive
GitHub workflow (``.github/workflows/keep-alive.yml``) pings the API's
``/api/v1/health`` endpoint, but operators sometimes need to confirm the
worker specifically is consuming tasks. This task is that probe.

Return shape is intentionally stable: any monitoring integration that
reads ``status`` and ``worker`` keeps working across worker redeploys.
"""

from __future__ import annotations

import socket
from datetime import UTC, datetime

from worker.app import celery_app


@celery_app.task(name="worker_health")
def worker_health() -> dict[str, str]:
    """Return a tiny liveness payload. No I/O, no DB, no logger writes."""
    return {
        "status": "ok",
        "worker": socket.gethostname(),
        "timestamp": datetime.now(UTC).isoformat(),
    }
