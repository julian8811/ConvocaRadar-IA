"""Tests for the ``POST /api/v1/auth/change-password`` endpoint (PR2-3).

The endpoint is authenticated: the request must come with a valid JWT cookie
or ``Authorization: Bearer`` header carrying ``scope="access"`` (PR1's claim
scheme). On success it:

1. verifies ``current_password`` against ``user.password_hash``;
2. rejects with 400 when the current password is wrong;
3. rejects with 422 when the new password is below 10 chars (Pydantic);
4. updates ``User.password_hash`` and bumps ``User.password_changed_at``;
5. writes an ``AuditLog`` row with ``action="change_password"``;
6. returns 204 No Content.

These tests are integration tests — they hit the real FastAPI app via
``TestClient`` and write to the test SQLite DB.
"""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.db.seed import seed
from app.db.session import SessionLocal
from app.main import app
from app.models import AuditLog, Organization, Role, User


def _create_user_with_token(*, email: str, password: str) -> tuple[str, str]:
    """Create a fresh user and return (access_token, user_id).

    Mirrors the helper used elsewhere in the auth tests: a known user in
    a known org, plus a freshly-minted access token. The token is the
    PRIMARY auth path; the cookie path is covered in test_api.py.
    """
    seed()
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert org is not None
        org_id = org.id  # capture inside the session
        existing = db.scalar(select(User).where(User.email == email))
        if existing is not None:
            db.delete(existing)
            db.commit()
        user = User(
            email=email,
            name="Change PW Test",
            password_hash=hash_password(password),
            role=Role.member.value,
            organization_id=org_id,
        )
        db.add(user)
        db.commit()
        user_id = user.id
    finally:
        db.close()
    token = create_access_token(user_id, extra={"organization_id": org_id}, scope="access")
    return token, user_id


def _get_user(email: str) -> User | None:
    db = SessionLocal()
    try:
        return db.scalar(select(User).where(User.email == email))
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_change_password_success_returns_204_and_updates_hash() -> None:
    """Happy path: a valid current password + valid new password returns 204.

    The new hash must be a different value from the old one (proof the
    update landed) and the user must be able to log in with the new
    password (proof the hash format is compatible with verify_password).
    """
    token, _ = _create_user_with_token(
        email="cp-success@example.com",
        password="old-password-1",
    )
    c = TestClient(app)
    response = c.post(
        "/api/v1/auth/change-password",
        json={"current_password": "old-password-1", "new_password": "new-password-1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 204, (
        f"Expected 204 from /auth/change-password on happy path, got "
        f"{response.status_code}: {response.text}"
    )
    # Hash must have changed
    user = _get_user("cp-success@example.com")
    assert user is not None
    assert user.password_hash != hash_password("old-password-1"), (
        "User.password_hash was not updated on /auth/change-password success."
    )
    # Login with new password must succeed
    login_resp = c.post(
        "/api/v1/auth/login",
        json={"email": "cp-success@example.com", "password": "new-password-1"},
    )
    assert login_resp.status_code == 200, (
        f"Login with new password failed after change-password: "
        f"{login_resp.status_code}: {login_resp.text}"
    )


def test_change_password_success_bumps_password_changed_at() -> None:
    """On success, ``User.password_changed_at`` is updated to ~now.

    PR1's claim check in ``get_current_user`` relies on this column
    being bumped. If the bump is missing, the next login of a user
    whose session was already authenticated will continue to use the
    stale JWT — the entire password-change audit-trail mechanism breaks.
    """
    token, _ = _create_user_with_token(
        email="cp-bump@example.com",
        password="old-password-2",
    )
    c = TestClient(app)
    before = datetime.utcnow()
    response = c.post(
        "/api/v1/auth/change-password",
        json={"current_password": "old-password-2", "new_password": "new-password-2"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 204
    after = datetime.utcnow()
    user = _get_user("cp-bump@example.com")
    assert user is not None
    assert user.password_changed_at is not None, (
        "User.password_changed_at was not bumped on /auth/change-password success. "
        "The JWT-invalidation contract from PR1 will not fire."
    )
    # The bumped timestamp must fall in the window around "now"
    bumped = user.password_changed_at
    if bumped.tzinfo is None:
        bumped = bumped.replace(tzinfo=None)
    assert before.replace(tzinfo=None) <= bumped <= after.replace(tzinfo=None) + __import__("datetime").timedelta(seconds=2), (
        f"password_changed_at={bumped} is outside the expected window "
        f"[{before}, {after}]. The bump is using the wrong clock source."
    )


def test_change_password_success_writes_audit_log() -> None:
    """On success, an AuditLog row with action='change_password' is written.

    The audit log is the security trail — a future SOC2 review will
    ask "show me every password change in the last 90 days". Missing
    audit entries on the password endpoint = critical control gap.
    """
    token, user_id = _create_user_with_token(
        email="cp-audit@example.com",
        password="old-password-3",
    )
    c = TestClient(app)
    response = c.post(
        "/api/v1/auth/change-password",
        json={"current_password": "old-password-3", "new_password": "new-password-3"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 204
    db = SessionLocal()
    try:
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.user_id == user_id,
                AuditLog.action == "change_password",
            )
        )
        assert audit is not None, (
            "No AuditLog row with action='change_password' was written. "
            "The audit trail is missing for this security-sensitive endpoint."
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_change_password_wrong_current_password_returns_400() -> None:
    """Wrong current_password → 400 with the documented detail.

    The detail message must NOT leak whether the user exists; the
    contract is "Current password is incorrect" so a phishing site
    cannot enumerate accounts from the change-password endpoint.
    """
    token, _ = _create_user_with_token(
        email="cp-wrong@example.com",
        password="right-password-1",
    )
    c = TestClient(app)
    response = c.post(
        "/api/v1/auth/change-password",
        json={"current_password": "WRONG", "new_password": "new-password-4"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400, (
        f"Expected 400 on wrong current_password, got {response.status_code}: "
        f"{response.text}"
    )
    detail = response.json().get("detail", "")
    assert "incorrect" in detail.lower() or "current" in detail.lower(), (
        f"Expected detail to mention 'current' or 'incorrect', got {detail!r}."
    )
    # Hash must NOT have changed
    user = _get_user("cp-wrong@example.com")
    assert user is not None
    assert verify_password_against_user("right-password-1", user.password_hash), (
        "User.password_hash was modified despite wrong current_password — "
        "the wrong-password branch is not preventing the update."
    )


def test_change_password_short_new_password_returns_422() -> None:
    """A 9-character new_password fails at the Pydantic layer (422).

    The schema validation must run BEFORE the handler. A 500 here
    means the schema is not wired up correctly.
    """
    token, _ = _create_user_with_token(
        email="cp-short@example.com",
        password="right-password-2",
    )
    c = TestClient(app)
    response = c.post(
        "/api/v1/auth/change-password",
        json={"current_password": "right-password-2", "new_password": "short"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422, (
        f"Expected 422 on short new_password, got {response.status_code}: "
        f"{response.text}"
    )
    # Hash must NOT have changed
    user = _get_user("cp-short@example.com")
    assert user is not None
    assert verify_password_against_user("right-password-2", user.password_hash), (
        "User.password_hash was modified despite a 422 response — the schema "
        "validation is not running before the handler."
    )


def test_change_password_unauthenticated_returns_401() -> None:
    """Calling the endpoint without a valid access token returns 401.

    The endpoint is auth-only — the unauthenticated branch must reject
    the request before any DB lookup or password check.
    """
    c = TestClient(app)
    response = c.post(
        "/api/v1/auth/change-password",
        json={"current_password": "anything", "new_password": "new-password-5"},
    )
    assert response.status_code == 401, (
        f"Expected 401 on unauthenticated /auth/change-password, got "
        f"{response.status_code}: {response.text}"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def verify_password_against_user(plaintext: str, stored_hash: str) -> bool:
    """Re-export the local verify_password without importing at module top.

    Importing at module top would cause a collection-time cycle in some
    test environments; lazy import keeps the tests robust.
    """
    from app.core.security import verify_password

    return verify_password(plaintext, stored_hash)
