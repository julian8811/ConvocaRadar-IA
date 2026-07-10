"""Tests for the ``POST /api/v1/auth/reset-password`` endpoint (PR2-5).

The endpoint accepts ``{token, new_password}`` and:

1. Decodes the JWT and validates the signature.
2. Rejects when the scope is not ``password_reset`` (constant detail).
3. Rejects when ``password_changed_at`` claim is stale — i.e. the user
   has changed their password since the reset was issued, which means
   the new claim on the live row no longer matches the claim baked
   into the JWT.
4. On success: updates the password hash, bumps ``password_changed_at``,
   writes an ``AuditLog`` row, returns 204.
5. The ``password_changed_at`` bump invalidates ALL in-flight reset
   tokens for the same user — the second reset attempt with the same
   token fails with the constant detail.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import create_access_token, create_reset_token, hash_password
from app.db.seed import seed
from app.db.session import SessionLocal
from app.main import app
from app.models import AuditLog, Organization, Role, User


def _create_user(*, email: str) -> str:
    """Create a known user and return the user_id. Idempotent across runs."""
    seed()
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert org is not None
        org_id = org.id
        existing = db.scalar(select(User).where(User.email == email))
        if existing is not None:
            db.delete(existing)
            db.commit()
        user = User(
            email=email,
            name="Reset PW Test",
            password_hash=hash_password("original-password-1"),
            role=Role.member.value,
            organization_id=org_id,
        )
        db.add(user)
        db.commit()
        return user.id
    finally:
        db.close()


def _get_user(email: str) -> User | None:
    db = SessionLocal()
    try:
        return db.scalar(select(User).where(User.email == email))
    finally:
        db.close()


def _mint_reset_token(user_id: str, *, password_changed_at: int = 0) -> str:
    """Mint a JWT the same way the forgot-password endpoint does.

    Uses ``create_reset_token`` (signed with ``reset_token_secret``) so
    the reset-password endpoint's ``decode_reset_token`` can decode it.
    """
    return create_reset_token(
        user_id,
        extra={"password_changed_at": password_changed_at},
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_reset_password_success_returns_204_and_updates_hash() -> None:
    """A valid reset JWT + 10+ char new password returns 204.

    The user must be able to log in with the new password. The new
    ``password_changed_at`` is bumped, which invalidates the JWT used
    here.
    """
    user_id = _create_user(email="reset-success@example.com")
    token = _mint_reset_token(user_id)
    c = TestClient(app)
    response = c.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "brand-new-secret-1"},
    )
    assert response.status_code == 204, (
        f"Expected 204 on valid reset, got {response.status_code}: {response.text}"
    )
    # Login with new password must succeed
    login = c.post(
        "/api/v1/auth/login",
        json={"email": "reset-success@example.com", "password": "brand-new-secret-1"},
    )
    assert login.status_code == 200, (
        f"Login with the new password failed after reset: {login.status_code}: {login.text}"
    )
    # Login with original password must fail
    old_login = c.post(
        "/api/v1/auth/login",
        json={"email": "reset-success@example.com", "password": "original-password-1"},
    )
    assert old_login.status_code == 401, (
        f"Login with the OLD password should fail after reset, got {old_login.status_code}"
    )


def test_reset_password_success_writes_audit_log() -> None:
    """On success, an AuditLog row with action='password_reset' is written.

    The exact action name in the orchestrator's spec is
    ``"password_reset_completed"``; the design doc uses ``"password_reset"``.
    We accept either — but the row must exist with the user_id of the
    reset user.
    """
    user_id = _create_user(email="reset-audit@example.com")
    token = _mint_reset_token(user_id)
    c = TestClient(app)
    response = c.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "brand-new-secret-2"},
    )
    assert response.status_code == 204
    db = SessionLocal()
    try:
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.user_id == user_id,
                AuditLog.action.in_(["password_reset", "password_reset_completed"]),
            )
        )
        assert audit is not None, (
            "No AuditLog row with a password-reset action was written. "
            "The audit trail is missing for this security-sensitive endpoint."
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Reject paths
# ---------------------------------------------------------------------------


def test_reset_password_expired_jwt_returns_400() -> None:
    """A JWT with ``exp`` in the past is rejected with the constant detail.

    The detail must be the constant "Reset token is invalid or expired"
    so a phishing site cannot distinguish "expired" from "wrong scope"
    from "bad signature".
    """
    settings = get_settings()
    user_id = _create_user(email="reset-expired@example.com")
    expired = jwt.encode(
        {
            "sub": user_id,
            "exp": datetime.now(UTC) - timedelta(hours=2),
            "iat": datetime.now(UTC) - timedelta(hours=3),
            "scope": "password_reset",
            "password_changed_at": 0,
        },
        settings.reset_token_secret,
        algorithm=settings.jwt_algorithm,
    )
    c = TestClient(app)
    response = c.post(
        "/api/v1/auth/reset-password",
        json={"token": expired, "new_password": "brand-new-secret-3"},
    )
    assert response.status_code in (400, 401), (
        f"Expected 400/401 on expired JWT, got {response.status_code}: {response.text}"
    )
    detail = response.json().get("detail", "")
    assert "invalid" in detail.lower() or "expired" in detail.lower(), (
        f"Expected constant detail about invalidity, got {detail!r}."
    )


def test_reset_password_wrong_scope_returns_400() -> None:
    """A JWT with ``scope="access"`` (not ``password_reset``) is rejected.

    This is the most important rejection — a stolen session token must
    NOT be usable to reset the password. If this test fails, the
    scope check on reset-password is missing.
    """
    user_id = _create_user(email="reset-wrong-scope@example.com")
    # Mint a token with reset_token_secret but wrong scope ("access").
    # This must fail at the scope check, not the signature check.
    wrong_scope_token = create_reset_token(user_id, scope="access")
    c = TestClient(app)
    response = c.post(
        "/api/v1/auth/reset-password",
        json={"token": wrong_scope_token, "new_password": "brand-new-secret-4"},
    )
    assert response.status_code in (400, 401), (
        f"Expected 400/401 on wrong-scope JWT, got {response.status_code}: {response.text}"
    )


def test_reset_password_mismatched_password_changed_at_returns_400() -> None:
    """A reset JWT issued BEFORE the user's password changed is rejected.

    Scenario: user requests a reset, gets a JWT with claim=0 (no prior
    change). User then changes their password via /change-password, so
    ``user.password_changed_at`` is now > 0. The original reset JWT
    has claim=0, the live row has claim>0 → mismatch → 400.
    """
    user_id = _create_user(email="reset-mismatch@example.com")
    # The test user starts with password_changed_at=None → epoch 0.
    # Mint a token with claim=0.
    stale_token = _mint_reset_token(user_id, password_changed_at=0)

    # Bump the user's password_changed_at directly to simulate a change
    # that happened AFTER the reset was issued.
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        assert user is not None
        user.password_changed_at = datetime.now(UTC)
        db.commit()
    finally:
        db.close()

    c = TestClient(app)
    response = c.post(
        "/api/v1/auth/reset-password",
        json={"token": stale_token, "new_password": "brand-new-secret-5"},
    )
    assert response.status_code in (400, 401), (
        f"Expected 400/401 on stale password_changed_at claim, got "
        f"{response.status_code}: {response.text}. The reset endpoint "
        "is not comparing the JWT claim against the live row — a user "
        "who changed their password after requesting a reset can still "
        "complete the stale reset."
    )


def test_reset_password_used_jwt_returns_400_on_second_use() -> None:
    """A reset JWT used successfully cannot be re-used (single-use claim).

    The bump of ``password_changed_at`` invalidates the token: the
    second attempt compares the (now stale) claim against the new
    live value, finds a mismatch, and rejects.
    """
    user_id = _create_user(email="reset-reuse@example.com")
    token = _mint_reset_token(user_id)
    c = TestClient(app)
    # First use: success
    r1 = c.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "brand-new-secret-6"},
    )
    assert r1.status_code == 204, f"First use should succeed, got {r1.status_code}: {r1.text}"
    # Second use: must fail
    r2 = c.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "another-secret-7"},
    )
    assert r2.status_code in (400, 401), (
        f"Second use of the same reset JWT should be rejected, got "
        f"{r2.status_code}: {r2.text}. A reset token is supposed to "
        "be single-use."
    )


def test_reset_password_short_new_password_returns_422() -> None:
    """A 9-char new password fails at the Pydantic layer (422).

    No DB write, no hash, no audit log — Pydantic must catch this
    before the route runs.
    """
    user_id = _create_user(email="reset-short@example.com")
    token = _mint_reset_token(user_id)
    c = TestClient(app)
    response = c.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "short"},
    )
    assert response.status_code == 422, (
        f"Expected 422 on short new_password, got {response.status_code}: {response.text}"
    )
    # Original password must still work — the schema validation ran before
    # any DB update.
    user = _get_user("reset-short@example.com")
    assert user is not None
    from app.core.security import verify_password
    assert verify_password("original-password-1", user.password_hash), (
        "User.password_hash was modified despite a 422 response — the "
        "schema validation is not running before the handler."
    )
