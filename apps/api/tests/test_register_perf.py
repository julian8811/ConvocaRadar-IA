"""GAP-1 (dashboard-redesign): POST /api/v1/auth/register must not block on
``seed_default_sources``. The synchronous call caused 30 s+ timeouts on
Render free tier; the fix is to enqueue the seeding work via Celery and
return the JWT in <1 s. CI is hermetic — the tests monkey-patch the
seed function and the Celery producer so no broker or DB writes are
required to exercise the contract.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

# Same env + sqlite convention as test_api.py; isolated file to keep the
# perf assertions out of the general auth/seed contract tests.
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_register_perf.db")
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("STORAGE_DIR", "./test_storage_register_perf")
os.environ.setdefault("SMTP_HOST", "")
os.environ.setdefault("JWT_SECRET", "a" * 64)
os.environ.setdefault("INTERNAL_API_KEY", "a" * 64)
os.environ.setdefault("BOOTSTRAP_SOURCES_ON_STARTUP", "false")

Path("test_register_perf.db").unlink(missing_ok=True)

from app.db.seed import seed  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402


# Latency budget: 1.0s gives cold CI a generous buffer; production p95
# target is <500 ms (per the design).
REGISTER_LATENCY_BUDGET_SECONDS = 1.0


def _client() -> TestClient:
    seed()
    return TestClient(app)


def _payload(prefix: str) -> dict[str, Any]:
    counter = getattr(_payload, "counter", 0) + 1
    setattr(_payload, "counter", counter)
    ts = int(time.time() * 1000)
    return {
        "email": f"{prefix}-{ts}-{counter}@example.com",
        "password": "strongpass123!",
        "name": f"User {counter}",
        "organization_name": f"Org {counter}",
        "organization_type": "startup",
        "country": "Mexico",
    }


def _assert_user_created(email: str) -> None:
    from app.models import User
    db = SessionLocal()
    try:
        assert db.scalar(select(User).where(User.email == email)) is not None
    finally:
        db.close()


def _try_patch_seed(monkeypatch: pytest.MonkeyPatch, replacement: Any) -> bool:
    """Try to monkey-patch ``app.api.v1.auth.seed_default_sources``.

    Returns True if the symbol is still imported by the handler (i.e.
    the inline call could still happen) and False if the import was
    dropped by WU-A4. The absence of the import is itself proof the
    inline call is gone — the handler cannot call a name it does not
    import.
    """
    try:
        monkeypatch.setattr("app.api.v1.auth.seed_default_sources", replacement)
        return True
    except AttributeError:
        return False


# ── WU-A1: latency budget ──────────────────────────────────────────────


def test_register_returns_under_1s(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the seed to sleep 5 s; assert register still returns in <1 s.

    If the handler still calls seed_default_sources inline, the slow
    patch pushes the request past the budget. If WU-A4 dropped the
    import, the patch fails fast and the latency check is a smoke
    assertion on the decoupled path.

    Also patch the Celery enqueue helper to a no-op so the latency
    budget is measured against the request-path work only — CI has no
    Redis broker and the real send_task call times out at ~20s.
    """
    def _slow(*_a: Any, **_k: Any) -> dict[str, int]:
        time.sleep(5)
        return {"inserted": 0, "updated": 0, "skipped": 0}

    inline_present = _try_patch_seed(monkeypatch, _slow)
    # CI is broker-less: short-circuit the enqueue so it does not block
    # on a real Redis connection (which would push elapsed well past 19s).
    monkeypatch.setattr(
        "app.api.v1.auth.enqueue_seed_default_sources",
        lambda _org_id: "fake-task-id-ci",
    )

    c = _client()
    started = time.perf_counter()
    response = c.post("/api/v1/auth/register", json=_payload("wu-a1"))
    elapsed = time.perf_counter() - started

    assert response.status_code == 200, response.text
    assert "access_token" in response.json()
    assert elapsed < REGISTER_LATENCY_BUDGET_SECONDS, (
        f"register took {elapsed:.3f}s; budget is {REGISTER_LATENCY_BUDGET_SECONDS}s"
        + ("" if inline_present else " (inline call gone; investigate other slow paths)")
    )


# ── WU-A4: inline call removed (raise + spy proofs) ─────────────────────


def test_register_succeeds_when_seed_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the inline seed raises, register must still return 200.

    The patch targets ``app.api.v1.auth.seed_default_sources``. If the
    handler still imports it, the patch triggers a raise inside the
    request. After WU-A4 the import is gone, so the raise never reaches
    the request path — which is the contract.
    """

    def _raise(*_a: Any, **_k: Any) -> dict[str, int]:
        raise RuntimeError("simulated seed failure")

    handler_imports_seed = _try_patch_seed(monkeypatch, _raise)

    c = _client()
    payload = _payload("wu-a4-raise")
    response = c.post("/api/v1/auth/register", json=payload)

    assert response.status_code == 200, response.text
    assert "access_token" in response.json()
    _assert_user_created(payload["email"])
    assert not handler_imports_seed, (
        "seed_default_sources is still imported into app.api.v1.auth — inline call not removed"
    )


def test_register_does_not_call_seed_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spy: seed_default_sources is never called from the request path.

    A recorder counts entries. With the inline call in place the count
    is 1; after WU-A4 the import is gone, so the spy is never installed
    and the count is 0.
    """
    call_log: list[str] = []

    def _spy(*_a: Any, **_k: Any) -> dict[str, int]:
        call_log.append("called")
        return {"inserted": 0, "updated": 0, "skipped": 0}

    handler_imports_seed = _try_patch_seed(monkeypatch, _spy)

    c = _client()
    payload = _payload("wu-a4-spy")
    response = c.post("/api/v1/auth/register", json=payload)

    assert response.status_code == 200, response.text
    assert call_log == [], f"seed_default_sources was called {len(call_log)} time(s) during register"
    _assert_user_created(payload["email"])
    assert not handler_imports_seed, (
        "seed_default_sources is still imported into app.api.v1.auth — inline call not removed"
    )


# ── WU-A2: enqueue helper contract ────────────────────────────────────


def test_enqueue_seed_default_sources_returns_task_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy path: the helper dispatches via Celery and returns the task id."""
    fake_id = "celery-task-id-12345"

    class _Result:
        id = fake_id

    class _Celery:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            self.sent: list[dict[str, Any]] = []

        def conf_update(self, **_k: Any) -> None:
            pass

        def send_task(self, *args: Any, **kwargs: Any) -> _Result:
            self.sent.append({"args": args, "kwargs": kwargs})
            return _Result()

    monkeypatch.setattr("celery.Celery", _Celery)

    from app.core.task_queue import enqueue_seed_default_sources
    assert enqueue_seed_default_sources("org-xyz") == fake_id


def test_enqueue_seed_default_sources_returns_none_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """send_task raises → helper logs a warning and returns None (never raises)."""

    class _Celery:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            pass

        def conf_update(self, **_k: Any) -> None:
            pass

        def send_task(self, *_a: Any, **_k: Any) -> None:
            raise ConnectionError("celery broker down")

    monkeypatch.setattr("celery.Celery", _Celery)

    from app.core.task_queue import enqueue_seed_default_sources
    assert enqueue_seed_default_sources("org-broken") is None


# ── WU-A6: warning on broker-down path ────────────────────────────────


def test_register_logs_warning_when_broker_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the enqueue helper returns None, the request still 200s and a
    structlog warning is emitted so on-call sees the broker outage.

    Structlog writes JSON to stdout directly (see app/core/logging.py),
    so pytest's caplog fixture cannot capture it; we use
    ``structlog.testing.capture_logs()`` instead.
    """
    import structlog

    monkeypatch.setattr(
        "app.api.v1.auth.enqueue_seed_default_sources",
        lambda _org_id: None,
    )

    c = _client()
    with structlog.testing.capture_logs() as captured:
        response = c.post("/api/v1/auth/register", json=_payload("wu-a6"))

    assert response.status_code == 200, response.text
    assert "access_token" in response.json()
    warning_events = [
        log for log in captured
        if log.get("log_level") == "warning" and "seed" in log.get("event", "")
    ]
    assert warning_events, (
        f"expected a structlog warning mentioning seed sources, "
        f"got events: {[log.get('event') for log in captured]}"
    )
