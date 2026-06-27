"""Performance + decoupling tests for POST /api/v1/auth/register.

GAP-1 (dashboard-redesign): the register endpoint must not block on source
seeding. The synchronous call to ``seed_default_sources`` was the root cause
of the 30 s timeout on Render free tier; the fix is to enqueue the seeding
work via Celery and return the JWT in <1 s.

These tests use ``monkeypatch`` on ``seed_default_sources`` so that the
in-process test client never actually seeds (CI is hermetic — there is no
Redis broker reachable from the test environment). The patches are scoped
per-test so they do not leak into other tests.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

# Re-use the same env + sqlite file convention as test_api.py so the new
# tests do not collide with the rest of the suite. Keeping them in a
# separate file also keeps the perf assertions out of the general
# auth/seed contract tests.
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
import app.main as app_main  # noqa: E402
from app.main import app  # noqa: E402


# Latency budget for the register endpoint on the median request. We use 1.0 s
# (per the design) as a generous upper bound so CI runners with cold caches
# do not flake; the p95 target is <500 ms in production.
REGISTER_LATENCY_BUDGET_SECONDS = 1.0


def _client() -> TestClient:
    """Build a fresh TestClient with the seed() bootstrap completed.

    Each test that calls _client() gets an isolated sqlite database because
    the module-level cleanup deletes the file before the first test
    import; subsequent tests share the file but seed() is idempotent.
    """
    seed()
    return TestClient(app)


def _unique_payload(email_prefix: str = "perf") -> dict[str, Any]:
    """Build a register payload with a unique email per test run."""
    # Use a microsecond timestamp + counter for collision-free emails across
    # repeated test invocations in the same CI job.
    counter = _unique_payload.counter = getattr(_unique_payload, "counter", 0) + 1  # type: ignore[attr-defined]
    timestamp = int(time.time() * 1000)
    return {
        "email": f"{email_prefix}-{timestamp}-{counter}@example.com",
        "password": "strongpass123!",
        "name": f"Perf User {counter}",
        "organization_name": f"Perf Org {counter}",
        "organization_type": "startup",
        "country": "Mexico",
    }


def _assert_user_created(email: str) -> None:
    """Sanity check: the user really is in the DB."""
    db = SessionLocal()
    try:
        from app.models import User  # local import to avoid circulars in test collection

        user = db.scalar(select(User).where(User.email == email))
        assert user is not None, f"User {email} was not created"
    finally:
        db.close()


def _handler_imports_seed_default_sources(monkeypatch: pytest.MonkeyPatch, replacement: Any) -> bool:
    """Try to patch ``app.api.v1.auth.seed_default_sources``.

    Returns True if the handler module still imports the symbol (so the
    patch went in and the request path could call it) and False if the
    import was dropped by the WU-A4 fix. Centralising this logic keeps
    each test readable and makes the contract obvious to future readers:
    the inline call is gone, and the absence of the import is itself
    proof.
    """
    try:
        monkeypatch.setattr("app.api.v1.auth.seed_default_sources", replacement)
        return True
    except AttributeError:
        return False


# ── WU-A1: register returns in <1 s when seed_default_sources is slow ─────


def test_register_returns_under_1s(monkeypatch: pytest.MonkeyPatch) -> None:
    """GAP-1: register must not block on seed_default_sources.

    The current implementation calls ``seed_default_sources`` synchronously
    inside the request handler. We monkey-patch it to sleep for 5 seconds;
    the test asserts the request still returns in <1 s. The test fails on
    the current code (RED) and goes green once the inline call is replaced
    with the Celery enqueue.
    """
    def _slow_seed(*_args: Any, **_kwargs: Any) -> dict[str, int]:
        # Simulate the cold-DB Render free-tier slowness that motivated
        # the original change. If the register handler calls this inline,
        # the request will take ~5 s and the assertion below will fail.
        time.sleep(5)
        return {"inserted": 0, "updated": 0, "skipped": 0}

    inline_call_still_present = _handler_imports_seed_default_sources(monkeypatch, _slow_seed)

    c = _client()
    payload = _unique_payload("wu-a1")

    started = time.perf_counter()
    response = c.post("/api/v1/auth/register", json=payload)
    elapsed = time.perf_counter() - started

    assert response.status_code == 200, response.text
    assert "access_token" in response.json()

    if inline_call_still_present:
        # RED phase: patch was applied; assert the budget is exceeded so
        # this test fails on the unfixed code.
        assert elapsed < REGISTER_LATENCY_BUDGET_SECONDS, (
            f"register took {elapsed:.3f}s; budget is {REGISTER_LATENCY_BUDGET_SECONDS}s. "
            "Inline seed_default_sources call has not been removed."
        )
    else:
        # GREEN phase: the import is gone so the inline call cannot run.
        # Still assert the wall-clock budget for safety.
        assert elapsed < REGISTER_LATENCY_BUDGET_SECONDS, (
            f"register took {elapsed:.3f}s; budget is {REGISTER_LATENCY_BUDGET_SECONDS}s "
            "even though seed_default_sources import is gone — investigate other slow paths."
        )


# ── WU-A4 helpers: register succeeds even when seed raises ──────────────


def test_register_succeeds_when_seed_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the seeding path raises, register must still return a Token.

    Proves the inline call has been removed: any exception from the old
    path would propagate to the client. With the Celery enqueue in place
    the function is decoupled from the request path.

    The monkeypatch targets ``app.api.v1.auth.seed_default_sources`` —
    if that symbol is still imported, the patch will trigger a raise
    inside the request. The absence of the import is itself proof that
    the inline call has been removed (the handler cannot call a name it
    does not import).
    """

    def _raising_seed(*_args: Any, **_kwargs: Any) -> dict[str, int]:
        raise RuntimeError("simulated seed failure")

    handler_imports_seed = _handler_imports_seed_default_sources(monkeypatch, _raising_seed)

    c = _client()
    payload = _unique_payload("wu-a4-raise")
    response = c.post("/api/v1/auth/register", json=payload)

    assert response.status_code == 200, response.text
    assert "access_token" in response.json()
    _assert_user_created(payload["email"])
    assert not handler_imports_seed, (
        "seed_default_sources is still imported into app.api.v1.auth — "
        "the inline call has not been removed."
    )


def test_register_does_not_call_seed_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spy test: seed_default_sources is never called during the request.

    A simple recorder counts how many times the function is entered from
    the request handler. With the inline call in place, the count is 1.
    After the fix, the count is 0 (the seeding is enqueued separately).

    The spy targets ``app.api.v1.auth.seed_default_sources``. If that
    symbol is not imported (post-WU-A4), the handler is decoupled by
    construction; the spy is never installed and the assertion passes.
    """
    call_log: list[str] = []

    def _spy_seed(*_args: Any, **_kwargs: Any) -> dict[str, int]:
        call_log.append("called")
        return {"inserted": 0, "updated": 0, "skipped": 0}

    handler_imports_seed = _handler_imports_seed_default_sources(monkeypatch, _spy_seed)

    c = _client()
    payload = _unique_payload("wu-a4-spy")
    response = c.post("/api/v1/auth/register", json=payload)

    assert response.status_code == 200, response.text
    assert call_log == [], (
        f"seed_default_sources was called {len(call_log)} time(s) during register. "
        "It must be decoupled from the request path."
    )
    _assert_user_created(payload["email"])
    assert not handler_imports_seed, (
        "seed_default_sources is still imported into app.api.v1.auth — "
        "the inline call has not been removed."
    )


# ── WU-A2 helpers: enqueue_seed_default_sources helper behaviour ─────────


def test_enqueue_seed_default_sources_returns_task_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """The helper dispatches via Celery and returns a non-empty task id."""
    fake_id = "celery-task-id-12345"

    class _FakeResult:
        id = fake_id

    class _FakeCelery:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            self.calls: list[dict[str, Any]] = []

        def conf_update(self, **_kwargs: Any) -> None:  # noqa: D401
            return None

        def send_task(self, *args: Any, **kwargs: Any) -> _FakeResult:
            self.calls.append({"args": args, "kwargs": kwargs})
            return _FakeResult()

    monkeypatch.setattr("celery.Celery", _FakeCelery)

    from app.core.task_queue import enqueue_seed_default_sources

    task_id = enqueue_seed_default_sources("org-xyz")
    assert task_id == fake_id


def test_enqueue_seed_default_sources_returns_none_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """When send_task raises, the helper logs a warning and returns None.

    Proves the contract documented in REQ-WORKER-2: the helper must never
    raise to the caller; a None return is the safe no-op signal.
    """

    class _ExplodingCelery:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def conf_update(self, **_kwargs: Any) -> None:  # noqa: D401
            return None

        def send_task(self, *_args: Any, **_kwargs: Any) -> None:
            raise ConnectionError("celery broker down")

    monkeypatch.setattr("celery.Celery", _ExplodingCelery)

    from app.core.task_queue import enqueue_seed_default_sources

    task_id = enqueue_seed_default_sources("org-broken")
    assert task_id is None


# ── WU-A6 helper: register logs warning when broker enqueue fails ────────


def test_register_logs_warning_when_broker_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """If enqueue_seed_default_sources returns None, the request still 200s
    AND a structlog warning is emitted so on-call sees the broker outage.

    REQ-AUTH-1 acceptance: the request must never fail because the
    background enqueue is unreachable; a warning must be visible to the
    operator so the broker outage is actionable.

    Structlog writes JSON to stdout directly (see app/core/logging.py) so
    pytest's caplog fixture cannot capture it; we use
    structlog.testing.capture_logs() instead, which patches the bound
    loggers in-place.
    """
    import structlog

    monkeypatch.setattr(
        "app.api.v1.auth.enqueue_seed_default_sources",
        lambda _org_id: None,
    )

    c = _client()
    payload = _unique_payload("wu-a6")
    with structlog.testing.capture_logs() as captured:
        response = c.post("/api/v1/auth/register", json=payload)

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
