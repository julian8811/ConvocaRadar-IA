"""Tests for the password_changed_at claim check in get_current_user.

PR1-4's design contract: ``get_current_user`` MUST reject tokens whose
``password_changed_at`` claim is stale (i.e. the user changed their
password after the token was issued). This is the mechanism that makes
``POST /auth/change-password`` invalidate every other in-flight session
for the same user — without it, a stolen cookie remains valid for its
full 1h lifetime even after a password change.

The test cases mirror the JWT claim check from PR1-4 of the design
doc. They live in this file (not test_auth.py) because they were
deferred from PR1 to PR2 — PR1 only wired the scope claim, leaving
the password_changed_at claim enforcement for the password-management
PR.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.seed import seed
from app.db.session import SessionLocal
from app.main import app
from app.models import Organization, Role, User


def _create_user_with_pca(*, email: str, password: str, password_changed_at: datetime | None) -> str:
    """Create a user with a controlled ``password_changed_at`` value.

    Returns the user_id. The value can be None (never changed) or any
    datetime for a controlled mismatch scenario.
    """
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
            name="PCA Claim Test",
            password_hash=hash_password(password),
            role=Role.member.value,
            organization_id=org_id,
            password_changed_at=password_changed_at,
        )
        db.add(user)
        db.commit()
        return user.id
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Contract: get_current_user rejects tokens whose password_changed_at
# claim does not match the live row
# ---------------------------------------------------------------------------


def test_get_current_user_rejects_token_with_stale_password_changed_at_claim() -> None:
    """A token whose ``password_changed_at`` claim is older than the live row is rejected.

    Scenario: user has password_changed_at = T1, gets a token with claim=T1.
    User then changes their password (live row bumps to T2 > T1). The
    original token's claim (T1) no longer matches the live row (T2) →
    401 "Token invalidated by password change".
    """
    settings = get_settings()
    initial_pca = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    user_id = _create_user_with_pca(
        email="pca-stale@example.com",
        password="old-password-1",
        password_changed_at=initial_pca,
    )
    # Mint a token with claim=initial_pca
    stale_token = jwt.encode(
        {
            "sub": user_id,
            "exp": datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes),
            "scope": "access",
            "password_changed_at": int(initial_pca.timestamp()),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    # Bump the live row to a later timestamp
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        assert user is not None
        user.password_changed_at = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
        db.commit()
    finally:
        db.close()

    c = TestClient(app)
    response = c.get("/api/v1/me", headers={"Authorization": f"Bearer {stale_token}"})
    assert response.status_code == 401, (
        f"Expected 401 for stale password_changed_at claim, got "
        f"{response.status_code}: {response.text}. The claim check in "
        "get_current_user is not wired up — a stolen cookie remains "
        "valid for its full 1h lifetime even after the user changes "
        "their password."
    )
    detail = response.json().get("detail", "")
    assert (
        "invalidated" in detail.lower()
        or "password change" in detail.lower()
        or "password_changed_at" in detail.lower()
    ), (
        f"Expected 401 detail to mention password change, got {detail!r}."
    )


def test_get_current_user_accepts_token_with_matching_password_changed_at_claim() -> None:
    """A token whose claim matches the live row is accepted (200 from /me).

    This is the happy path for the claim check — the check must not
    REJECT valid tokens. Without this guard, the claim check could
    false-positive and lock every user out at deploy time.
    """
    settings = get_settings()
    pca = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    user_id = _create_user_with_pca(
        email="pca-match@example.com",
        password="Sup3rStrong!",
        password_changed_at=pca,
    )
    token = jwt.encode(
        {
            "sub": user_id,
            "exp": datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes),
            "scope": "access",
            "password_changed_at": int(pca.timestamp()),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    c = TestClient(app)
    response = c.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, (
        f"Expected 200 for matching password_changed_at claim, got "
        f"{response.status_code}: {response.text}. The claim check is "
        "false-rejecting valid tokens."
    )


def test_get_current_user_accepts_legacy_token_without_password_changed_at_claim() -> None:
    """Tokens issued before this check existed (no claim) still work.

    Backward-compat: the missing claim defaults to 0, and a user with
    ``password_changed_at=None`` (epoch 0) matches. So pre-PR1 cookies
    remain valid for users who haven't changed their password since
    the migration.
    """
    settings = get_settings()
    user_id = _create_user_with_pca(
        email="pca-legacy@example.com",
        password="Sup3rStrong!",
        password_changed_at=None,  # treated as epoch 0
    )
    legacy_token = jwt.encode(
        {
            "sub": user_id,
            "exp": datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes),
            "scope": "access",
            # NO password_changed_at claim — pre-PR2 cookies
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    c = TestClient(app)
    response = c.get("/api/v1/me", headers={"Authorization": f"Bearer {legacy_token}"})
    assert response.status_code == 200, (
        f"Expected 200 for legacy (no-claim) token on a user with "
        f"password_changed_at=None, got {response.status_code}: {response.text}. "
        "The default for missing claim must be 0 (the migration's backfill value)."
    )


def test_get_current_user_rejects_legacy_token_when_user_has_changed_password() -> None:
    """A legacy (no-claim) token fails for a user who has changed their password.

    This is the PR1-4 migration edge case: a user with a pre-PR1 cookie
    (claim=0) has since changed their password via the new endpoint
    (live row > 0). The default-0 claim no longer matches → 401.
    """
    settings = get_settings()
    user_id = _create_user_with_pca(
        email="pca-legacy-stale@example.com",
        password="Sup3rStrong!",
        password_changed_at=datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
    )
    legacy_token = jwt.encode(
        {
            "sub": user_id,
            "exp": datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes),
            "scope": "access",
            # NO claim — defaults to 0
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    c = TestClient(app)
    response = c.get("/api/v1/me", headers={"Authorization": f"Bearer {legacy_token}"})
    assert response.status_code == 401, (
        f"Expected 401 for legacy (no-claim) token on a user who has "
        f"since changed their password, got {response.status_code}: "
        f"{response.text}. The migration backfill is not enforced — "
        "pre-PR1 cookies remain valid forever."
    )
