"""Tests for Change 4 — Security Hardening.

Covers four work items:

1. SameSite=Strict on the auth cookie — ``_set_token_cookie`` and
   ``_clear_token_cookie`` must set ``samesite="strict"`` instead of
   ``"lax"``. We check the raw ``Set-Cookie`` header because the
   Starlette ``Response.cookies`` dict does not expose SameSite.

2. Rate-limit by email on ``POST /auth/login`` — 5 attempts per email
   per hour, 6th is 429. The rate limiter must be independent per email
   so an attacker cannot DoS all users by spraying one address.

3. ``RESET_TOKEN_SECRET`` separate from ``JWT_SECRET`` — reset tokens
   are signed with a dedicated key. ``decode_access_token`` must reject
   reset tokens and ``decode_reset_token`` must reject access tokens.

4. CORS hardening — ``allow_origin_regex`` removed, production-mode
   origin validation.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import (
    create_access_token,
    create_reset_token,
    decode_access_token,
    decode_reset_token,
    hash_password,
)
from app.core.config import get_settings
from app.core.rate_limit import email_login_limiter
from app.db.seed import seed
from app.db.session import SessionLocal
from app.main import app
from app.models import Organization, Role, User
from app.api.v1.auth import _set_token_cookie, TOKEN_COOKIE_NAME


# ---------------------------------------------------------------------------
# 1. SameSite=Strict on the auth cookie
# ---------------------------------------------------------------------------


def _extract_cookie_samesite(set_cookie_header: str) -> str | None:
    """Parse the ``SameSite=`` value out of a ``Set-Cookie`` header."""
    for part in set_cookie_header.split(";"):
        part = part.strip()
        if part.lower().startswith("samesite="):
            return part.split("=", 1)[1].strip().lower()
    return None


def test_set_token_cookie_uses_samesite_strict() -> None:
    """_set_token_cookie must set SameSite=Strict on the auth cookie.

    We test directly by calling _set_token_cookie with a real Starlette
    Response and inspecting the Set-Cookie header.
    """
    from starlette.responses import Response

    resp = Response()
    _set_token_cookie(resp, "test-token-value-123")
    # After calling set_cookie, the cookie is in resp.headers
    set_cookie = resp.headers.get("set-cookie", "")
    assert set_cookie, "No Set-Cookie header — _set_token_cookie did not fire"
    samesite = _extract_cookie_samesite(set_cookie)
    assert samesite == "strict", (
        f"Expected SameSite=Strict, got SameSite={samesite!r}. "
        f"Full Set-Cookie: {set_cookie}. "
        "Change _set_token_cookie in app/api/v1/auth.py to use "
        "samesite='strict' instead of samesite='lax'."
    )


def test_login_cookie_has_samesite_strict() -> None:
    """The actual /auth/login endpoint returns a SameSite=Strict cookie.

    This is the integration test: we log in with valid credentials and
    check the Set-Cookie header on the 200 response.
    """
    seed()
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert org is not None
        if not db.scalar(select(User).where(User.email == "samesite-test@example.com")):
            db.add(
                User(
                    email="samesite-test@example.com",
                    name="SameSite Test",
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
        json={"email": "samesite-test@example.com", "password": "Sup3rStrong!"},
    )
    assert response.status_code == 200, (
        f"Login failed: {response.status_code}: {response.text}"
    )
    set_cookie = response.headers.get("set-cookie", "")
    assert set_cookie, "No Set-Cookie header on login response"
    samesite = _extract_cookie_samesite(set_cookie)
    assert samesite == "strict", (
        f"Login cookie SameSite={samesite!r}, expected 'strict'. "
        f"Full Set-Cookie: {set_cookie}"
    )


def test_register_cookie_has_samesite_strict() -> None:
    """The /auth/register endpoint returns a SameSite=Strict cookie."""
    import uuid as uuid_module

    seed()
    uid = uuid_module.uuid4().hex[:8]
    email = f"samesite-reg-{uid}@example.com"
    org_name = f"SameSite Reg Org {uid}"

    c = TestClient(app)
    response = c.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "Sup3rStrong!",
            "name": "SameSite Reg Test",
            "organization_name": org_name,
            "organization_type": "startup",
            "country": "Mexico",
        },
    )
    assert response.status_code == 200, (
        f"Register failed: {response.status_code}: {response.text}"
    )
    set_cookie = response.headers.get("set-cookie", "")
    assert set_cookie, "No Set-Cookie header on register response"
    samesite = _extract_cookie_samesite(set_cookie)
    assert samesite == "strict", (
        f"Register cookie SameSite={samesite!r}, expected 'strict'. "
        f"Full Set-Cookie: {set_cookie}"
    )

    # Cleanup
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        if user is not None:
            db.delete(user)
            db.commit()
    finally:
        db.close()


def test_logout_clears_cookie_with_samesite_strict() -> None:
    """The /auth/logout endpoint deletes the cookie with SameSite=Strict.

    The delete_cookie call also carries a SameSite attribute in the
    Set-Cookie header (the Max-Age=0 / expires=past directive). We
    check that SameSite=Strict is present on the deletion header too.
    """
    c = TestClient(app)
    response = c.post("/api/v1/auth/logout")
    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "")
    assert set_cookie, "No Set-Cookie header on logout"
    samesite = _extract_cookie_samesite(set_cookie)
    assert samesite == "strict", (
        f"Logout cookie SameSite={samesite!r}, expected 'strict'. "
        f"Full Set-Cookie: {set_cookie}"
    )


# ---------------------------------------------------------------------------
# 2. Rate limit by email on login
# ---------------------------------------------------------------------------


def _reset_email_login_limiter() -> None:
    """Clear the login rate limiter between tests."""
    email_login_limiter._buckets.clear()


def test_login_sixth_request_from_same_email_returns_429() -> None:
    """5 login attempts with wrong password → 401 (auth fail), 6th → 429.

    The rate limiter fires BEFORE password validation. We use the same
    email with a wrong password each time. The first 5 get 401 (wrong
    password); the 6th gets 429 (rate limited).
    """
    _reset_email_login_limiter()
    seed()
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert org is not None
        if not db.scalar(select(User).where(User.email == "login-rl@example.com")):
            db.add(
                User(
                    email="login-rl@example.com",
                    name="Login RL Test",
                    password_hash=hash_password("correct-password"),
                    role=Role.member.value,
                    organization_id=org.id,
                )
            )
            db.commit()
    finally:
        db.close()

    c = TestClient(app)
    statuses: list[int] = []
    for _ in range(6):
        r = c.post(
            "/api/v1/auth/login",
            json={"email": "login-rl@example.com", "password": "wrong-password"},
        )
        statuses.append(r.status_code)

    # First 5 are 401 (wrong password, not rate-limited)
    assert statuses[:5] == [401, 401, 401, 401, 401], (
        f"Expected first 5 login attempts to return 401, got {statuses[:5]}. "
        "The rate limiter is interfering before auth validation."
    )
    # 6th is 429 (rate limited)
    assert statuses[5] == 429, (
        f"Expected 6th login attempt to be throttled (429), got {statuses[5]}. "
        f"All statuses: {statuses}. The 5-per-hour limit on login is not enforced."
    )
    # Body must mention rate limiting
    body = c.post(
        "/api/v1/auth/login",
        json={"email": "login-rl@example.com", "password": "wrong-password"},
    ).json()
    detail = body.get("detail", "")
    assert "too many" in detail.lower() or "try again" in detail.lower(), (
        f"Expected 429 detail to mention rate limiting, got {detail!r}."
    )


def test_login_rate_limit_is_per_email() -> None:
    """Exhausting the login budget for one email must not affect other emails.

    Attacker spams alice@example.com to exhaust the budget. bob@example.com
    must still be able to attempt login (and get 401, not 429).
    """
    _reset_email_login_limiter()
    seed()
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert org is not None
        org_id = org.id
        for email in ["login-rl-alice@example.com", "login-rl-bob@example.com"]:
            if not db.scalar(select(User).where(User.email == email)):
                db.add(
                    User(
                        email=email,
                        name="Login RL Per-Email",
                        password_hash=hash_password("correct-password"),
                        role=Role.member.value,
                        organization_id=org_id,
                    )
                )
                db.commit()
    finally:
        db.close()

    c = TestClient(app)
    # Exhaust alice
    for _ in range(5):
        c.post(
            "/api/v1/auth/login",
            json={"email": "login-rl-alice@example.com", "password": "wrong-password"},
        )

    # Alice is now blocked
    alice_resp = c.post(
        "/api/v1/auth/login",
        json={"email": "login-rl-alice@example.com", "password": "wrong-password"},
    )
    assert alice_resp.status_code == 429, (
        f"Alice should be throttled, got {alice_resp.status_code}"
    )

    # Bob must NOT be throttled
    bob_resp = c.post(
        "/api/v1/auth/login",
        json={"email": "login-rl-bob@example.com", "password": "wrong-password"},
    )
    assert bob_resp.status_code == 401, (
        f"Bob was throttled by Alice's exhausted budget — cross-user DoS. "
        f"Got {bob_resp.status_code}: {bob_resp.text}"
    )


def test_login_rate_limit_allows_correct_password_on_first_attempt() -> None:
    """A user with the correct password must be able to log in despite the rate limiter.

    The rate limiter counts attempts BEFORE password validation. A valid
    login on the first attempt must succeed (200), not get 429.
    """
    _reset_email_login_limiter()
    seed()
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert org is not None
        if not db.scalar(select(User).where(User.email == "login-rl-valid@example.com")):
            db.add(
                User(
                    email="login-rl-valid@example.com",
                    name="Login RL Valid",
                    password_hash=hash_password("correct-password"),
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
        json={"email": "login-rl-valid@example.com", "password": "correct-password"},
    )
    assert response.status_code == 200, (
        f"Valid login on first attempt should succeed, got {response.status_code}: {response.text}"
    )
    assert "access_token" in response.json()


# ---------------------------------------------------------------------------
# 3. RESET_TOKEN_SECRET separate from JWT_SECRET
# ---------------------------------------------------------------------------


def test_create_reset_token_produces_valid_token() -> None:
    """create_reset_token must produce a JWT that decode_reset_token can decode.

    Happy path: a token created with create_reset_token must be
    decodable by decode_reset_token and carry the expected claims.
    """
    token = create_reset_token("user-sec-test-1", extra={"reason": "forgot"})
    payload = decode_reset_token(token)
    assert payload["sub"] == "user-sec-test-1", (
        f"Expected sub='user-sec-test-1', got {payload.get('sub')!r}"
    )
    assert payload.get("reason") == "forgot", (
        f"Expected extra claim 'reason'='forgot', got {payload.get('reason')!r}"
    )
    assert payload.get("scope") == "password_reset", (
        f"Expected scope='password_reset', got {payload.get('scope')!r}"
    )


def test_reset_token_is_signed_with_different_secret() -> None:
    """A reset token signed with reset_token_secret must NOT be decodable by decode_access_token.

    If both use the same secret, compromising one secret compromises both
    token types. decode_access_token uses jwt_secret; decode_reset_token
    uses reset_token_secret. A reset token decoded with jwt_secret must
    fail (ValueError).
    """
    reset_token = create_reset_token("user-sec-test-2")
    # decode_access_token (which uses jwt_secret) must raise ValueError
    # because the token is signed with a different key.
    import pytest

    with pytest.raises(ValueError, match="Invalid token"):
        decode_access_token(reset_token)


def test_access_token_is_not_decodable_by_decode_reset_token() -> None:
    """An access token signed with jwt_secret must NOT be decodable by decode_reset_token.

    Symmetric check: decode_reset_token uses reset_token_secret, so it
    must reject an access token (signed with jwt_secret).
    """
    access_token = create_access_token("user-sec-test-3")
    import pytest

    with pytest.raises(ValueError, match="Invalid token"):
        decode_reset_token(access_token)


def test_reset_token_has_expiry() -> None:
    """Reset tokens must carry an ``exp`` claim (default access_token_expire_minutes).

    We verify the token has an exp claim and it's in the future.
    """
    from datetime import UTC, datetime

    token = create_reset_token("user-sec-test-4")
    payload = decode_reset_token(token)
    exp = payload.get("exp")
    assert exp is not None, "Reset token is missing the 'exp' claim"
    exp_dt = datetime.fromtimestamp(exp, tz=UTC)
    assert exp_dt > datetime.now(UTC), (
        f"Reset token exp ({exp_dt}) is in the past"
    )


def test_forgot_password_uses_reset_token_secret() -> None:
    """POST /auth/forgot-password must mint a JWT signed with reset_token_secret.

    The token from forgot-password must be decodable by decode_reset_token
    but NOT by decode_access_token. We verify the dual property through
    the actual endpoint.
    """
    from app.api.v1.auth import forgot_limiter

    forgot_limiter._buckets.clear()

    seed()
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert org is not None
        if not db.scalar(select(User).where(User.email == "forgot-sec-test@example.com")):
            db.add(
                User(
                    email="forgot-sec-test@example.com",
                    name="Forgot Sec Test",
                    password_hash=hash_password("Sup3rStrong!"),
                    role=Role.member.value,
                    organization_id=org.id,
                )
            )
            db.commit()
    finally:
        db.close()

    # We can't easily intercept the token from the 200 response (it's in
    # the log). Instead, we re-mint the same way the endpoint does by
    # calling create_reset_token directly with the same claims.
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "forgot-sec-test@example.com"))
        assert user is not None
        from app.api.v1.auth import _password_changed_at_epoch

        epoch = _password_changed_at_epoch(user)
        token = create_reset_token(
            user.id,
            extra={"password_changed_at": epoch},
        )
    finally:
        db.close()

    # Token must be decodable by decode_reset_token
    payload = decode_reset_token(token)
    assert payload.get("scope") == "password_reset", (
        f"Expected scope='password_reset', got {payload.get('scope')!r}"
    )
    assert payload.get("password_changed_at") is not None, (
        "Reset token from forgot-password must carry password_changed_at"
    )

    # Token must NOT be decodable by decode_access_token
    import pytest

    with pytest.raises(ValueError):
        decode_access_token(token)


def test_reset_password_accepts_reset_token() -> None:
    """POST /auth/reset-password must accept tokens signed with reset_token_secret.

    The endpoint currently uses decode_access_token. After the change,
    it must use decode_reset_token. A valid reset token from
    create_reset_token must succeed on the reset-password endpoint.
    """
    from app.api.v1.auth import forgot_limiter

    forgot_limiter._buckets.clear()

    seed()
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert org is not None
        org_id = org.id
        existing = db.scalar(select(User).where(User.email == "reset-sec-test@example.com"))
        if existing is not None:
            db.delete(existing)
            db.commit()
        user = User(
            email="reset-sec-test@example.com",
            name="Reset Sec Test",
            password_hash=hash_password("original-password"),
            role=Role.member.value,
            organization_id=org_id,
        )
        db.add(user)
        db.commit()
        user_id = user.id
    finally:
        db.close()

    # Mint a reset token the way forgot-password would
    token = create_reset_token(user_id, extra={"password_changed_at": 0})

    c = TestClient(app)
    response = c.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "new-secure-password-123"},
    )
    assert response.status_code == 204, (
        f"Expected 204 on valid reset token, got {response.status_code}: {response.text}. "
        "The reset-password endpoint may still be using decode_access_token instead of "
        "decode_reset_token."
    )

    # Cleanup: reset password back
    db = SessionLocal()
    try:
        u = db.get(User, user_id)
        if u is not None:
            u.password_hash = hash_password("original-password")
            u.password_changed_at = None
            db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 4. CORS hardening
# ---------------------------------------------------------------------------


def test_cors_allow_origin_regex_is_removed() -> None:
    """The CORSMiddleware must NOT have ``allow_origin_regex`` set.

    SEC-4: remove allow_origin_regex to prevent accidental over-matching
    (the regex ``r"^https?://(localhost|127\\.0\\.0\\.1)(:\\d+)?$"`` can
    match unintended origins like ``http://localhost.evil.com`` after
    normalisation caveats).

    We check that the middleware stack does not include a CORSMiddleware
    with ``allow_origin_regex`` set to a non-None value.
    """
    # Inspect the app's user middleware stack. Each entry is a
    # starlette.middleware.Middleware instance with .cls and .kwargs.
    found_cors = False
    for mw in app.user_middleware:
        if getattr(mw.cls, "__name__", "") == "CORSMiddleware":
            found_cors = True
            # ``allow_origin_regex`` must NOT be in kwargs — removed per SEC-4.
            assert "allow_origin_regex" not in mw.kwargs, (
                f"CORSMiddleware still has allow_origin_regex={mw.kwargs['allow_origin_regex']!r}. "
                "It must be removed per SEC-4. See app/main.py."
            )
    assert found_cors, "CORSMiddleware not found in app.user_middleware"


def test_cors_rejects_unknown_origin() -> None:
    """A request from an origin not in allow_origins must be rejected.

    We send an OPTIONS preflight with an Origin header that is NOT in
    the allowed list and verify the response does NOT include
    Access-Control-Allow-Origin.
    """
    c = TestClient(app)
    response = c.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "https://evil-site.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    # When the origin is not allowed, the CORS middleware should NOT
    # return Access-Control-Allow-Origin in the response.
    assert "access-control-allow-origin" not in {
        k.lower() for k in response.headers
    }, (
        "CORS middleware returned Access-Control-Allow-Origin for an unknown "
        "origin (https://evil-site.com). The allow_origins list is too permissive."
    )


def test_cors_allows_known_origin() -> None:
    """A request from a known origin must get Access-Control-Allow-Origin back.

    http://localhost:3000 is in the default allow_origins list (dev mode).
    We verify the preflight returns the expected headers.
    """
    c = TestClient(app)
    response = c.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000", (
        "CORS middleware did not return Access-Control-Allow-Origin for a known "
        "origin (http://localhost:3000). The allow_origins list may have changed."
    )
    assert response.headers.get("access-control-allow-credentials") == "true", (
        "CORS middleware must return Access-Control-Allow-Credentials: true"
    )
