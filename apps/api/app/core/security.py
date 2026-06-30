from datetime import UTC, datetime, timedelta
import base64
import hashlib
import hmac
import os
from typing import Any

from jose import JWTError, jwt

from app.core.config import get_settings

PBKDF2_ITERATIONS = 390_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def create_access_token(
    subject: str,
    extra: dict[str, Any] | None = None,
    scope: str = "access",
) -> str:
    """Mint a JWT for ``subject``.

    Parameters
    ----------
    subject:
        The user id (or any stable identifier) to embed as the ``sub`` claim.
    extra:
        Optional bag of extra claims. Anything the caller wants in the
        payload (e.g. ``{"organization_id": "..."}``).
    scope:
        The token's intended purpose. Defaults to ``"access"`` for the
        login/register flow. PR2's password-reset flow overrides this
        with ``"password_reset"`` so the same helper can mint both kinds
        of tokens without the ``get_current_user`` dep accepting a
        reset token on a protected route.

    Notes
    -----
    The ``scope`` claim is checked by ``app.api.deps.get_current_user``:
    only ``scope="access"`` tokens are allowed on protected routes.
    Tokens without a ``scope`` claim (issued before PR1) are accepted as
    ``"access"`` for backward compat — see the decode default in
    ``get_current_user``.
    """
    settings = get_settings()
    expires = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {"sub": subject, "exp": expires, "scope": scope}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise ValueError("Invalid token") from exc
