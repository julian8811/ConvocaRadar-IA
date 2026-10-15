"""Registration-mode gate on POST /api/v1/auth/register (T2 seguridad-remediacion).

Contract:
- ``REGISTRATION_MODE=open`` (default): current behavior, no gate.
- ``REGISTRATION_MODE=closed``: every register attempt is 403.
- ``REGISTRATION_MODE=domain``: only emails whose domain is listed in
  ``REGISTRATION_ALLOWED_DOMAINS`` (comma-separated) may register; others 403.
- Unknown mode: fail closed (403).

The gate fires AFTER the T1 rate-limit check and BEFORE any DB query.

RED tests: fail at import/startup until the settings exist and the gate
is enforced (settings default to open, so unconfigured runs behave as today).
"""

from __future__ import annotations

import uuid as uuid_module

from fastapi.testclient import TestClient


def _register_once(c: TestClient, email: str, org: str) -> int:
    r = c.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "Sup3rStrong!",
            "name": "Reg Mode Test",
            "organization_name": org,
            "organization_type": "startup",
            "country": "Mexico",
        },
    )
    return r.status_code


def test_register_closed_mode_returns_403(monkeypatch) -> None:
    """REGISTRATION_MODE=closed must reject every registration with 403."""
    from app.core.config import get_settings

    monkeypatch.setenv("REGISTRATION_MODE", "closed")
    get_settings.cache_clear()
    try:
        from app.api.v1.auth import register_limiter
        from app.db.seed import seed
        from app.main import app

        register_limiter._buckets.clear()
        seed()
        c = TestClient(app)
        uid = uuid_module.uuid4().hex[:8]
        status = _register_once(c, f"regmode-closed-{uid}@example.com", f"Reg Mode Closed {uid}")
        assert status == 403, f"Expected closed mode to return 403, got {status}."
    finally:
        get_settings.cache_clear()


def test_register_domain_mode_allows_listed_domain(monkeypatch) -> None:
    """Listed domains register normally (200 first time)."""
    from app.core.config import get_settings

    monkeypatch.setenv("REGISTRATION_MODE", "domain")
    monkeypatch.setenv("REGISTRATION_ALLOWED_DOMAINS", "colmayor.edu.co")
    get_settings.cache_clear()
    try:
        from app.api.v1.auth import register_limiter
        from app.db.seed import seed
        from app.db.session import SessionLocal
        from app.main import app
        from app.models import User
        from sqlalchemy import select

        register_limiter._buckets.clear()
        seed()
        c = TestClient(app)
        uid = uuid_module.uuid4().hex[:8]
        email = f"regmode-ok-{uid}@colmayor.edu.co"
        status = _register_once(c, email, f"Reg Mode Ok {uid}")
        assert status == 200, f"Expected listed domain to register (200), got {status}."
        db = SessionLocal()
        try:
            user = db.scalar(select(User).where(User.email == email))
            if user is not None:
                db.delete(user)
                db.commit()
        finally:
            db.close()
    finally:
        get_settings.cache_clear()


def test_register_domain_mode_rejects_other_domain(monkeypatch) -> None:
    """Non-listed domains get 403 and must NOT create any user."""
    from app.core.config import get_settings

    monkeypatch.setenv("REGISTRATION_MODE", "domain")
    monkeypatch.setenv("REGISTRATION_ALLOWED_DOMAINS", "colmayor.edu.co")
    get_settings.cache_clear()
    try:
        from app.api.v1.auth import register_limiter
        from app.db.seed import seed
        from app.db.session import SessionLocal
        from app.main import app
        from app.models import User
        from sqlalchemy import select

        register_limiter._buckets.clear()
        seed()
        c = TestClient(app)
        uid = uuid_module.uuid4().hex[:8]
        email = f"regmode-no-{uid}@evil.example.com"
        status = _register_once(c, email, f"Reg Mode No {uid}")
        assert status == 403, f"Expected non-listed domain to return 403, got {status}."
        db = SessionLocal()
        try:
            assert db.scalar(select(User).where(User.email == email)) is None, (
                "Domain gate returned 403 but the user row was still created."
            )
        finally:
            db.close()
    finally:
        get_settings.cache_clear()


def test_register_unknown_mode_fails_closed(monkeypatch) -> None:
    """A misconfigured mode must fail closed (403), never open."""
    from app.core.config import get_settings

    monkeypatch.setenv("REGISTRATION_MODE", "nonsense")
    get_settings.cache_clear()
    try:
        from app.api.v1.auth import register_limiter
        from app.db.seed import seed
        from app.main import app

        register_limiter._buckets.clear()
        seed()
        c = TestClient(app)
        uid = uuid_module.uuid4().hex[:8]
        status = _register_once(c, f"regmode-x-{uid}@example.com", f"Reg Mode X {uid}")
        assert status == 403, f"Expected unknown mode to fail closed (403), got {status}."
    finally:
        get_settings.cache_clear()
