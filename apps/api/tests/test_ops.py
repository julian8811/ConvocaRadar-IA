"""Tests for ``GET /api/v1/ops/worker-health`` (PR6).

The endpoint dispatches the ``worker_health`` Celery task and waits up
to 5 seconds for the result. It exists so operators can confirm the
worker (separate from the API) is alive and consuming tasks. The task
itself is a tiny no-I/O function in
``apps/worker/worker/tasks/health.py``; the contract is:

* 200 OK with ``{"status": "ok", "worker": "<hostname>", "timestamp": "..."}``
  when the worker is reachable and replies inside the 5s window.
* 504 Gateway Timeout when the worker accepts the task but does not
  reply within 5s.
* 503 Service Unavailable when the API is configured to run inline
  (``USE_WORKER=false``) — there is no worker to probe.
* 401/403 when the caller is not authenticated as an admin.

The endpoint is admin-only so a non-admin caller cannot use it as a
worker-discovery side channel.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_ops.db")
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("STORAGE_DIR", "./test_storage_ops")
os.environ.setdefault("SMTP_HOST", "")
os.environ.setdefault("JWT_SECRET", "a" * 64)
os.environ.setdefault("INTERNAL_API_KEY", "a" * 64)
os.environ.setdefault("BOOTSTRAP_SOURCES_ON_STARTUP", "false")
os.environ.setdefault("DISABLE_INPROCESS_CELERY", "1")

Path("test_ops.db").unlink(missing_ok=True)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.seed import seed  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Organization, Role, User  # noqa: E402


ADMIN_EMAIL = "admin@convocaradar.io"
ADMIN_PASSWORD = "ConvocaRadarLocal123!"


@pytest.fixture
def client() -> TestClient:
    """Build a hermetic client with the admin user seeded."""
    seed()
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert org is not None, "seed() must create the local org"
        if not db.scalar(select(User).where(User.email == ADMIN_EMAIL)):
            db.add(
                User(
                    email=ADMIN_EMAIL,
                    name="Admin ConvocaRadar",
                    password_hash=hash_password(ADMIN_PASSWORD),
                    role=Role.admin.value,
                    organization_id=org.id,
                )
            )
            db.commit()
    finally:
        db.close()
    return TestClient(app)


def _admin_token(c: TestClient) -> str:
    response = c.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _member_token(c: TestClient) -> str:
    """Create + login a non-admin user to verify the admin-only guard."""
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert org is not None
        email = "member@convocaradar.io"
        if not db.scalar(select(User).where(User.email == email)):
            db.add(
                User(
                    email=email,
                    name="Member User",
                    password_hash=hash_password("MemberLocal123!"),
                    role=Role.member.value,
                    organization_id=org.id,
                )
            )
            db.commit()
    finally:
        db.close()
    response = c.post(
        "/api/v1/auth/login",
        json={"email": "member@convocaradar.io", "password": "MemberLocal123!"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_worker_health_returns_200_with_worker_payload(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy path: the worker replies inside the 5s window with a stable payload."""
    from app.api.v1 import ops as ops_module

    monkeypatch.setattr(ops_module.settings, "use_worker", True)

    class _FakeAsyncResult:
        def __init__(self, payload: dict[str, str]) -> None:
            self._payload = payload

        def get(self, timeout: float | None = None) -> dict[str, str]:
            return self._payload

    captured: dict[str, object] = {}

    def _fake_send_task(name: str, *args: object, **kwargs: object) -> _FakeAsyncResult:
        captured["name"] = name
        return _FakeAsyncResult(
            {
                "status": "ok",
                "worker": socket.gethostname(),
                "timestamp": "2026-06-30T00:00:00+00:00",
            }
        )

    monkeypatch.setattr(ops_module._celery_app, "send_task", _fake_send_task)

    response = client.get(
        "/api/v1/ops/worker-health",
        headers={"Authorization": f"Bearer {_admin_token(client)}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["worker"] == socket.gethostname()
    assert body["timestamp"] == "2026-06-30T00:00:00+00:00"
    assert captured["name"] == "worker_health"


def test_worker_health_returns_504_on_timeout(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the worker accepts the task but does not reply in 5s, return 504."""
    from app.api.v1 import ops as ops_module

    monkeypatch.setattr(ops_module.settings, "use_worker", True)

    class _FakeAsyncResult:
        def get(self, timeout: float | None = None) -> dict[str, str]:
            raise TimeoutError("worker did not respond within 5s")

    monkeypatch.setattr(ops_module._celery_app, "send_task", lambda *a, **kw: _FakeAsyncResult())

    response = client.get(
        "/api/v1/ops/worker-health",
        headers={"Authorization": f"Bearer {_admin_token(client)}"},
    )
    assert response.status_code == 504, response.text
    body = response.json()
    assert "timeout" in body.get("detail", "").lower()


def test_worker_health_returns_503_when_worker_disabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If USE_WORKER=false the API has no worker to probe — return 503, not 500."""
    from app.api.v1 import ops as ops_module

    # Flip the setting the endpoint reads. The endpoint checks
    # ``settings.use_worker``; the test conftest defaults it to False
    # because there's no Redis broker in CI. We assert it directly.
    monkeypatch.setattr(ops_module.settings, "use_worker", False)

    # Also patch send_task so we can prove the endpoint short-circuited
    # BEFORE touching the broker.
    called = {"value": False}

    def _fake_send_task(*args: object, **kwargs: object) -> object:
        called["value"] = True
        raise AssertionError("send_task must not be called when use_worker is False")

    monkeypatch.setattr(ops_module._celery_app, "send_task", _fake_send_task)

    response = client.get(
        "/api/v1/ops/worker-health",
        headers={"Authorization": f"Bearer {_admin_token(client)}"},
    )
    assert response.status_code == 503, response.text
    assert called["value"] is False


def test_worker_health_requires_admin(client: TestClient) -> None:
    """Non-admin caller must be rejected with 403, not leak worker info."""
    response = client.get(
        "/api/v1/ops/worker-health",
        headers={"Authorization": f"Bearer {_member_token(client)}"},
    )
    assert response.status_code == 403, response.text


def test_worker_health_requires_authentication(client: TestClient) -> None:
    """Unauthenticated callers get 401, not 200."""
    response = client.get("/api/v1/ops/worker-health")
    assert response.status_code == 401, response.text
