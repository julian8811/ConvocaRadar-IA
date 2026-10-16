"""Rate limit on POST /api/v1/auth/register (T1 seguridad-remediacion).

Contract: 5 register attempts per email per hour, 6th is 429 — the same
documented contract as login (5/h) and forgot-password (5/h). The check
fires BEFORE any DB query or password hash, like login does.

RED test: fails at import until `register_limiter` exists in app.api.v1.auth.
"""

from __future__ import annotations

import uuid as uuid_module

from fastapi.testclient import TestClient
from sqlalchemy import select


def _reset_register_limiter() -> None:
    """Clear the register rate limiter between tests."""
    from app.api.v1.auth import register_limiter

    register_limiter._buckets.clear()


def test_register_sixth_request_from_same_email_returns_429() -> None:
    """Same email 6x: 200 (created), 4x 409 (exists), 6th 429 (throttled)."""
    from app.api.v1.auth import register_limiter  # noqa: F401 (RED if missing)
    from app.db.seed import seed
    from app.db.session import SessionLocal
    from app.main import app
    from app.models import User

    _reset_register_limiter()
    seed()

    uid = uuid_module.uuid4().hex[:8]
    email = f"register-rl-{uid}@example.com"
    payload = {
        "email": email,
        "password": "Sup3rStrong!",
        "name": "Register RL Test",
        "organization_name": f"Register RL Org {uid}",
        "organization_type": "startup",
        "country": "Mexico",
    }

    c = TestClient(app)
    statuses: list[int] = []
    for _ in range(6):
        r = c.post("/api/v1/auth/register", json=payload)
        statuses.append(r.status_code)

    assert statuses[0] == 200, (
        f"Expected first register to create (200), got {statuses[0]}: "
        f"{c.post('/api/v1/auth/register', json=payload).text[:200]}"
    )
    assert statuses[1:5] == [409, 409, 409, 409], (
        f"Expected repeats 2-5 to be 409 (exists), got {statuses[1:5]}."
    )
    assert statuses[5] == 429, (
        f"Expected 6th register to be throttled (429), got {statuses[5]}. "
        f"All statuses: {statuses}. The 5-per-hour limit on register is not enforced."
    )

    # Cleanup: remove the user so the test is idempotent across runs
    # (same precedent as test_auth.py — the org row stays).
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        if user is not None:
            db.delete(user)
            db.commit()
    finally:
        db.close()
