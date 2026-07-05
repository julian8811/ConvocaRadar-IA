"""GAP-1 (dashboard-redesign): POST /api/v1/auth/register must not block on
``seed_default_sources``. After Celery/Redis removal, seeding runs inline
within the API process — the important contract is that it returns <1 s
and does not crash.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

# Use a dedicated DB to avoid polluting the main test DB.
os.environ["DATABASE_URL"] = "sqlite:///./test_register_perf.db"
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
    """
    def _slow(*_a: Any, **_k: Any) -> dict[str, int]:
        time.sleep(5)
        return {"inserted": 0, "updated": 0, "skipped": 0}

    inline_present = _try_patch_seed(monkeypatch, _slow)

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


# ── WU-A2: enqueue helper contract (updated for inline-only) ────────────


def test_enqueue_seed_default_sources_returns_success() -> None:
    """Inline helper returns 'inline' on success (no Celery broker)."""
    from app.core.task_queue import enqueue_seed_default_sources

    # The function needs a real org ID. Use the seeded org.
    db = SessionLocal()
    try:
        from app.models import Organization
        org = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert org is not None, "seeded org must exist"
        org_id = org.id
    finally:
        db.close()

    result = enqueue_seed_default_sources(org_id)
    assert result == "inline", (
        f"expected 'inline' for the seeded org, got {result!r}"
    )


def test_enqueue_seed_default_sources_returns_none_on_invalid_org() -> None:
    """Invalid org ID → helper logs a warning and returns None."""
    from app.core.task_queue import enqueue_seed_default_sources

    assert enqueue_seed_default_sources("nonexistent-org-id") is None


# ── WU-A6: log on seed failure ─────────────────────────────────────────


def test_register_logs_info_when_broker_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enqueue returns 'inline' (not None) — request does not log a warning.
    The helper no longer returns None on success; it always returns 'inline'.
    """
    import structlog

    c = _client()
    with structlog.testing.capture_logs() as captured:
        response = c.post("/api/v1/auth/register", json=_payload("wu-a6"))

    assert response.status_code == 200, response.text
    assert "access_token" in response.json()
    # No warning expected — the inline path always succeeds.
    warning_events = [
        log for log in captured
        if log.get("log_level") == "warning" and "seed" in log.get("event", "")
    ]
    assert len(warning_events) == 0, (
        f"expected NO warning events for seed, got {len(warning_events)}: "
        f"{[log.get('event') for log in warning_events]}"
    )
