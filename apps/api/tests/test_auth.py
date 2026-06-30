"""Tests for the JWT auth claim scheme (PR1 of tier-2-production-readiness).

The auth foundation introduces two new claims on every issued access token:

- ``scope`` (default ``"access"``) — distinguishes login/register tokens from
  later "password_reset" tokens. The ``get_current_user`` dep rejects
  ``password_reset`` tokens on protected routes.
- ``password_changed_at`` (epoch seconds, default ``0``) — the user's
  password-changed timestamp at the moment the JWT was minted. ``get_current_user``
  compares this claim against the live row and returns 401 if it has been
  bumped since the token was issued.

The tests in this file cover the JWT-level contract. Route-level tests (e.g.
``/me`` rejecting a wrong-scope token) live in ``test_api.py`` to keep the
separation between unit and integration layers.
"""

from __future__ import annotations

from app.core.security import create_access_token, decode_access_token


# ---------------------------------------------------------------------------
# PR1-2: create_access_token bakes in scope="access" by default
# ---------------------------------------------------------------------------


def test_create_access_token_default_scope_is_access() -> None:
    """A token created with no explicit scope must still carry scope='access'.

    This is the backward-compat contract: existing callers that do not pass
    ``scope=...`` get the same behavior as the new callers that do. Without
    this guarantee, get_current_user's scope check (PR1-4) would need a
    second fallback for "missing scope" — adding a code path that
    silently allows wrong-scope tokens.
    """
    token = create_access_token("user-123")
    payload = decode_access_token(token)
    assert payload["scope"] == "access", (
        f"Expected default scope='access', got {payload.get('scope')!r}. "
        "create_access_token must inject scope='access' into the payload "
        "even when the caller does not pass it explicitly."
    )


def test_create_access_token_explicit_scope_is_preserved() -> None:
    """A token created with an explicit scope=... must carry that scope.

    PR2 (account recovery) will mint tokens with scope='password_reset' from
    the same helper. If scope='password_reset' is silently overwritten to
    'access', the reset flow becomes a self-DoS — the user gets a token, but
    protected routes reject it and the reset-password endpoint also rejects
    it for the same reason.
    """
    token = create_access_token("user-123", scope="password_reset")
    payload = decode_access_token(token)
    assert payload["scope"] == "password_reset", (
        f"Expected explicit scope='password_reset' to be preserved, got "
        f"{payload.get('scope')!r}. The scope parameter is being dropped or "
        "overwritten — check create_access_token's signature and payload assembly."
    )


def test_create_access_token_still_embeds_extra_claims() -> None:
    """Backwards-compat: extra={...} claims (e.g. organization_id) must still land in the payload.

    The login and register endpoints pass ``extra={"organization_id": ...}``
    alongside the new ``scope=...`` argument. If the refactor of
    ``create_access_token`` accidentally clobbers the ``extra`` dict, the
    cookie will not contain ``organization_id`` and downstream code that
    reads it (e.g. multi-tenant filtering) will break.
    """
    token = create_access_token("user-123", extra={"organization_id": "org-abc", "role": "admin"})
    payload = decode_access_token(token)
    assert payload.get("organization_id") == "org-abc", (
        f"Extra claim 'organization_id' missing from payload. Got keys: "
        f"{sorted(payload)}. The refactor of create_access_token must not "
        "drop the extra={...} dict."
    )
    assert payload.get("role") == "admin", (
        f"Extra claim 'role' missing from payload. Got keys: {sorted(payload)}."
    )


def test_create_access_token_subject_is_still_the_sub_claim() -> None:
    """Sanity: the new scope=... parameter must not replace or shadow the sub claim.

    Existing code calls ``create_access_token(user.id)`` and expects the
    subject to be the user ID. If ``scope=...`` accidentally overwrites
    ``sub`` (e.g. because of a payload.update ordering bug), every JWT in
    the system becomes invalid — the user ID is lost, get_current_user
    raises 401 on every request, and the entire product goes down.
    """
    token = create_access_token("user-abc-789")
    payload = decode_access_token(token)
    assert payload["sub"] == "user-abc-789", (
        f"Expected sub='user-abc-789', got {payload.get('sub')!r}. "
        "The scope=... refactor must not overwrite the sub claim."
    )


# ---------------------------------------------------------------------------
# PR1-2 / PR1-4 cross-cutting: backward-compat decode of legacy tokens
# ---------------------------------------------------------------------------


def test_decode_access_token_accepts_token_without_scope_claim() -> None:
    """Tokens issued before PR1 have no scope claim — decode must not raise.

    Some users will keep their browser session cookie through the deploy.
    That cookie was minted by the pre-PR1 code and has no ``scope`` claim.
    If ``decode_access_token`` (or its callers) crash on the missing key,
    every active user is logged out at deploy time. The legacy token must
    be accepted as scope='access' (the implicit default).
    """
    from app.core.config import get_settings
    from jose import jwt

    settings = get_settings()
    # Mint a token with NO scope claim, mimicking pre-PR1 behavior
    legacy_payload = {
        "sub": "user-legacy-1",
        "exp": jwt.get_unverified_claims({})["exp"] if False else 0,  # not used; see below
    }
    # Build a real token without an "scope" claim
    from datetime import UTC, datetime, timedelta

    legacy_payload = {
        "sub": "user-legacy-1",
        "exp": datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes),
        "organization_id": "org-legacy-1",
    }
    legacy_token = jwt.encode(legacy_payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    # decode_access_token must not raise on the missing-scope token
    payload = decode_access_token(legacy_token)
    assert "sub" in payload, "decode_access_token dropped the sub claim"
    assert payload["sub"] == "user-legacy-1"
    # It is the caller's responsibility (get_current_user, PR1-4) to default
    # scope to "access" when the claim is missing. The helper itself only
    # validates the signature and the expiry.


# ---------------------------------------------------------------------------
# PR1-3 / PR1-4 cross-cutting: register & login endpoints embed scope=access
# ---------------------------------------------------------------------------


def test_login_jwt_includes_scope_claim() -> None:
    """POST /auth/login must mint a token whose decoded payload has scope='access'.

    This is the integration test for PR1-2 from the route side: we hit the
    real /auth/login endpoint, capture the access_token, decode it, and
    verify the scope. If the endpoint is forgotten in the PR1-2 refactor,
    this test fails with a clear message.
    """
    from fastapi.testclient import TestClient

    from app.db.seed import seed
    from app.db.session import SessionLocal
    from sqlalchemy import select

    from app.main import app
    from app.models import Organization, Role, User
    from app.core.security import hash_password

    # Set up: a known user in a known org
    seed()
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert org is not None
        if not db.scalar(select(User).where(User.email == "scope-test@example.com")):
            db.add(
                User(
                    email="scope-test@example.com",
                    name="Scope Test",
                    password_hash=hash_password("Sup3rStrong!"),
                    role=Role.member.value,
                    organization_id=org.id,
                )
            )
            db.commit()
    finally:
        db.close()

    c = TestClient(app)
    response = c.post(
        "/api/v1/auth/login",
        json={"email": "scope-test@example.com", "password": "Sup3rStrong!"},
    )
    assert response.status_code == 200, (
        f"Expected 200 from /auth/login, got {response.status_code}: {response.text}"
    )
    token = response.json()["access_token"]
    payload = decode_access_token(token)
    assert payload.get("scope") == "access", (
        f"Decoded /auth/login JWT has scope={payload.get('scope')!r}, expected 'access'. "
        "The login endpoint must pass scope='access' to create_access_token."
    )


def test_register_jwt_includes_scope_claim() -> None:
    """POST /auth/register must mint a token whose decoded payload has scope='access'.

    New users get a JWT on register. If scope is missing from that JWT,
    the user's first authenticated request (which happens seconds after
    registration) returns 401. The user thinks registration succeeded but
    they cannot do anything — a critical onboarding regression.
    """
    import uuid as uuid_module

    from fastapi.testclient import TestClient

    from app.db.seed import seed
    from app.db.session import SessionLocal
    from sqlalchemy import select

    from app.main import app
    from app.models import User

    seed()
    # Use a unique email AND a unique org name per test run. The org name
    # becomes a unique slug (slugify), and Organization.slug has a unique
    # index — a duplicate slug triggers an IntegrityError that the
    # register route surfaces as a 500.
    uid = uuid_module.uuid4().hex[:8]
    email = f"register-scope-{uid}@example.com"
    org_name = f"Register Scope Org {uid}"

    c = TestClient(app)
    response = c.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "Sup3rStrong!",
            "name": "Register Scope Test",
            "organization_name": org_name,
            "organization_type": "startup",
            "country": "Mexico",
        },
    )
    assert response.status_code == 200, (
        f"Expected 200 from /auth/register, got {response.status_code}: {response.text}"
    )
    token = response.json()["access_token"]
    payload = decode_access_token(token)
    assert payload.get("scope") == "access", (
        f"Decoded /auth/register JWT has scope={payload.get('scope')!r}, expected 'access'. "
        "The register endpoint must pass scope='access' to create_access_token."
    )

    # Cleanup: remove the user we just created so the test is idempotent across runs
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        if user is not None:
            db.delete(user)
            db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# PR1-4: get_current_user rejects tokens whose scope is not 'access'
# ---------------------------------------------------------------------------


def test_get_current_user_accepts_legacy_token_without_scope_claim() -> None:
    """A token issued before PR1 (no scope claim) must still work on /me.

    The scope=... default in get_current_user is the backward-compat bridge.
    If it is missing, every active user with a pre-PR1 cookie gets 401 on
    their next request — a hard logout for the entire installed base at
    deploy time. The cookie remains valid; only the scope claim is missing.
    """
    from datetime import UTC, datetime, timedelta

    from fastapi.testclient import TestClient
    from jose import jwt

    from app.core.config import get_settings
    from app.db.seed import seed
    from app.db.session import SessionLocal
    from sqlalchemy import select

    from app.main import app
    from app.models import Organization, Role, User
    from app.core.security import hash_password

    settings = get_settings()
    seed()
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert org is not None
        # Capture the org id inside the try block — accessing org.id outside
        # the session triggers a lazy load and DetachedInstanceError.
        org_id = org.id
        if not db.scalar(select(User).where(User.email == "legacy-token@example.com")):
            db.add(
                User(
                    email="legacy-token@example.com",
                    name="Legacy Token Test",
                    password_hash=hash_password("Sup3rStrong!"),
                    role=Role.member.value,
                    organization_id=org_id,
                )
            )
            db.commit()
        user = db.scalar(select(User).where(User.email == "legacy-token@example.com"))
        assert user is not None
        user_id = user.id
    finally:
        db.close()

    # Mint a token with NO scope claim, mimicking pre-PR1 behavior
    legacy_payload = {
        "sub": user_id,
        "exp": datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes),
        "organization_id": org_id,
    }
    legacy_token = jwt.encode(legacy_payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    c = TestClient(app)
    response = c.get("/api/v1/me", headers={"Authorization": f"Bearer {legacy_token}"})
    assert response.status_code == 200, (
        f"Expected 200 from /me with a legacy (no-scope) token, got "
        f"{response.status_code}: {response.text}. The backward-compat default "
        "for missing scope=... is not wired up in get_current_user — every "
        "pre-PR1 cookie will 401 at deploy time."
    )
    assert response.json()["email"] == "legacy-token@example.com"


def test_get_current_user_rejects_password_reset_scope() -> None:
    """A token minted with scope='password_reset' must NOT authenticate /me.

    The whole point of the scope split is to prevent token reuse. A
    password-reset link that accidentally works on /me (or any other
    protected route) would let anyone who phished a reset email from the
    user's inbox act as that user for the lifetime of the token — exactly
    the scenario the scope was added to prevent.
    """
    from fastapi.testclient import TestClient

    from app.db.seed import seed
    from app.db.session import SessionLocal
    from sqlalchemy import select

    from app.main import app
    from app.models import Organization, Role, User
    from app.core.security import hash_password

    seed()
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert org is not None
        if not db.scalar(select(User).where(User.email == "reset-scope-test@example.com")):
            db.add(
                User(
                    email="reset-scope-test@example.com",
                    name="Reset Scope Test",
                    password_hash=hash_password("Sup3rStrong!"),
                    role=Role.member.value,
                    organization_id=org.id,
                )
            )
            db.commit()
    finally:
        db.close()

    # Mint a token with scope='password_reset' directly (simulates PR2's
    # /auth/forgot-password flow). We use create_access_token with the
    # explicit scope parameter (PR1-2).
    reset_token = create_access_token("user-with-reset-token", scope="password_reset")

    c = TestClient(app)
    # NOTE: the token's sub does not match a real user, so even if the scope
    # check were skipped, /me would 401 with "User not found". The point of
    # this test is that the scope check fires FIRST, returning the
    # scope-specific error. We assert on the response body, not the user.
    response = c.get("/api/v1/me", headers={"Authorization": f"Bearer {reset_token}"})
    assert response.status_code == 401, (
        f"Expected 401 from /me with scope='password_reset' token, got "
        f"{response.status_code}: {response.text}. The scope check in "
        "get_current_user is not wired up — the token is being accepted."
    )
    # The detail message should mention the scope, not "user not found"
    # (which would mean the scope check was skipped and only the user
    # lookup failed).
    detail = response.json().get("detail", "")
    assert "scope" in detail.lower() or "password_reset" in detail.lower() or detail == "Invalid token", (
        f"Expected 401 detail to indicate a scope rejection, got {detail!r}. "
        "If detail == 'User not found', the scope check ran AFTER the user "
        "lookup and the password_reset token was decoded. If detail == "
        "'Invalid token', the signature check ran first and we never got to "
        "the scope check at all — the test should be re-evaluated."
    )
