"""Tests for the DB-aware healthcheck split.

These tests assert the live/ready/readiness contract:
- GET /api/v1/health       -> 200 with database='reachable' when DB is up
- GET /api/v1/health       -> 503 with database='unreachable' when DB is down
- GET /api/v1/health/live  -> 200 always (no DB call) — for k8s liveness
- GET /api/v1/health/ready -> same contract as /api/v1/health — for k8s readiness
- All three endpoints bypass the rate limiter (no 429 even after the limit)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_convocaradar.db")
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("STORAGE_DIR", "./test_storage")
os.environ.setdefault("SMTP_HOST", "")
os.environ.setdefault("INTERNAL_API_KEY", "test_internal_key")
os.environ.setdefault("BOOTSTRAP_SOURCES_ON_STARTUP", "false")
os.environ.setdefault("SENTRY_DSN", "")

# Make the production main module importable without side effects
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

import app.main as app_main  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    """A TestClient that DOES NOT raise on unhandled exceptions (so we can
    trigger error responses cleanly)."""
    return TestClient(app_main.app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# /api/v1/health (the existing endpoint) — now DB-aware
# ---------------------------------------------------------------------------


def test_health_returns_200_when_db_is_reachable(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "database": "reachable"}


def test_health_returns_503_when_db_is_unreachable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Force the healthcheck's DB probe to raise — endpoint must surface 503."""
    from app.db import session as session_module

    class _ConnectCtx:
        def __enter__(self):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

        def __exit__(self, *args):
            return False

    def _connect_raises(*args, **kwargs):
        return _ConnectCtx()

    monkeypatch.setattr(session_module.engine, "connect", _connect_raises)
    response = client.get("/api/v1/health")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unreachable"


# ---------------------------------------------------------------------------
# /api/v1/health/live — process liveness, no DB
# ---------------------------------------------------------------------------


def test_live_returns_200_with_no_db_call(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Liveness must never touch the database — guard against accidental
    coupling by patching the engine's connect to raise."""
    from app.db import session as session_module

    def _connect_raises(*args, **kwargs):
        raise AssertionError("liveness probe must not hit the database")

    monkeypatch.setattr(session_module.engine, "connect", _connect_raises)
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body.get("service") == "convocaradar-api"


# ---------------------------------------------------------------------------
# /api/v1/health/ready — same contract as /api/v1/health
# ---------------------------------------------------------------------------


def test_ready_returns_200_when_db_is_reachable(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "database": "reachable"}


def test_ready_returns_503_when_db_is_unreachable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db import session as session_module

    class _ConnectCtx:
        def __enter__(self):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

        def __exit__(self, *args):
            return False

    def _connect_raises(*args, **kwargs):
        return _ConnectCtx()

    monkeypatch.setattr(session_module.engine, "connect", _connect_raises)
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unreachable"


# ---------------------------------------------------------------------------
# Rate limiter bypass — health endpoints must never 429
# ---------------------------------------------------------------------------


def test_health_endpoints_bypass_rate_limiter(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the rate limiter accidentally started counting health probes, an
    orchestrator (k8s, Render) hammering /health/live every second would
    trigger 429. Guard the bypass explicitly."""
    monkeypatch.setattr(app_main.settings, "rate_limit_requests_per_minute", 1)
    app_main.app.state.rate_limits.clear()

    # Reset the bucket for whichever host the test client uses
    for _ in range(5):
        for path in (
            "/api/v1/health",
            "/api/v1/health/live",
            "/api/v1/health/ready",
        ):
            response = client.get(path)
            assert response.status_code in {200, 503}, (
                f"Rate limiter hit on {path}: {response.status_code} {response.text}"
            )


# ---------------------------------------------------------------------------
# Production wiring — handlers actually exist on the app object
# ---------------------------------------------------------------------------


def test_health_routes_registered() -> None:
    # `app.routes` can contain non-API route objects (e.g. _IncludedRouter
    # from nested include_router calls) which do not expose `.path`. Filter
    # to attribute-having routes so the set comprehension does not raise
    # AttributeError in CI environments where the order/contents of
    # app.routes differ slightly from local.
    paths = {route.path for route in app_main.app.routes if hasattr(route, "path")}
    assert "/api/v1/health" in paths
    assert "/api/v1/health/live" in paths
    assert "/api/v1/health/ready" in paths
