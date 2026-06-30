"""Tests for the Pydantic schemas introduced in PR2 of tier-2-production-readiness.

The account-recovery endpoints accept three new request bodies:
``ChangePasswordRequest``, ``ForgotPasswordRequest``, ``ResetPasswordRequest``.
Each has a small set of invariants we pin down at the schema layer (so the
endpoint can stay focused on business logic) — the new password is at
least 10 characters (matches ``RegisterRequest.password``), the email is
a valid email address, and the token is a non-empty string.

These are pure Pydantic tests — no database, no FastAPI.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
)


# ---------------------------------------------------------------------------
# ChangePasswordRequest
# ---------------------------------------------------------------------------


def test_change_password_request_accepts_valid_payload() -> None:
    """Happy path: a 10+ char current + 10+ char new password round-trips.

    Pydantic's ``model_dump`` is the contract the endpoint relies on — if
    the field names change, the endpoint breaks silently. This test pins
    the field names too.
    """
    payload = ChangePasswordRequest(
        current_password="old-secret-123",
        new_password="new-secret-456",
    )
    dumped = payload.model_dump()
    assert dumped["current_password"] == "old-secret-123"
    assert dumped["new_password"] == "new-secret-456"


def test_change_password_request_rejects_short_new_password() -> None:
    """A 9-character new_password is below the project standard (10) — must 422.

    The whole point of the validation is to keep weak passwords out of
    the DB. A 9-char password is hashed and stored with the same
    ceremony as a strong one; the only thing that matters is the
    length check fires BEFORE the route handler runs.
    """
    with pytest.raises(ValidationError) as exc_info:
        ChangePasswordRequest(current_password="old-secret-123", new_password="short")
    errors = exc_info.value.errors()
    assert any("new_password" in str(err.get("loc", ())) for err in errors), (
        f"Expected the validation error to point at new_password, got: {errors}"
    )


def test_change_password_request_allows_exactly_10_char_new_password() -> None:
    """Boundary: the limit is inclusive. A 10-char password is allowed.

    Off-by-one in the min_length comparison is the classic PR1-style
    bug — a 10-char password should be allowed, an 9-char one rejected.
    """
    payload = ChangePasswordRequest(current_password="x", new_password="a" * 10)
    assert len(payload.new_password) == 10


def test_change_password_request_requires_current_password_non_empty() -> None:
    """An empty current_password is meaningless — must raise.

    The endpoint will call ``verify_password(current, hash)``; passing
    an empty string works against ``pbkdf2_sha256`` (it just hashes the
    empty string) but would silently always fail. Catching it at the
    schema layer gives the client a clearer 422.
    """
    with pytest.raises(ValidationError):
        ChangePasswordRequest(current_password="", new_password="a" * 10)


# ---------------------------------------------------------------------------
# ForgotPasswordRequest
# ---------------------------------------------------------------------------


def test_forgot_password_request_accepts_valid_email() -> None:
    """A normal email address round-trips through the schema."""
    payload = ForgotPasswordRequest(email="user@example.com")
    assert payload.email == "user@example.com"


def test_forgot_password_request_rejects_invalid_email() -> None:
    """A non-email string (no '@') must raise ValidationError.

    Pydantic's ``EmailStr`` is the contract — if we drop it, the route
    handler will pass garbage to the rate limiter (lowercased) and
    potentially DoS the in-memory bucket.
    """
    with pytest.raises(ValidationError):
        ForgotPasswordRequest(email="not-an-email")


def test_forgot_password_request_rejects_empty_string() -> None:
    """An empty string is not a valid email — must raise."""
    with pytest.raises(ValidationError):
        ForgotPasswordRequest(email="")


# ---------------------------------------------------------------------------
# ResetPasswordRequest
# ---------------------------------------------------------------------------


def test_reset_password_request_accepts_valid_token_and_password() -> None:
    """Happy path: non-empty token + 10+ char new password round-trip."""
    payload = ResetPasswordRequest(
        token="eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1MSJ9.signature",
        new_password="new-secret-456",
    )
    assert payload.token.startswith("eyJ")
    assert payload.new_password == "new-secret-456"


def test_reset_password_request_rejects_short_new_password() -> None:
    """The new_password limit applies here too — no exceptions for reset.

    A 9-char password is below the project standard. Pydantic must catch
    it before the endpoint hashes and stores it.
    """
    with pytest.raises(ValidationError) as exc_info:
        ResetPasswordRequest(token="any-token", new_password="short")
    errors = exc_info.value.errors()
    assert any("new_password" in str(err.get("loc", ())) for err in errors), (
        f"Expected validation error to point at new_password, got: {errors}"
    )


def test_reset_password_request_requires_token_non_empty() -> None:
    """An empty token would decode to garbage and is meaningless — must raise."""
    with pytest.raises(ValidationError):
        ResetPasswordRequest(token="", new_password="a" * 10)
