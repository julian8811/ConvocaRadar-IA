"""Session-cookie flags driven by COOKIE_SECURE (plain-HTTP LAN support).

Default (COOKIE_SECURE unset/True, current production behavior):
``Secure`` + ``SameSite=None`` so cross-origin frontends keep working.

Plain-HTTP LAN (``COOKIE_SECURE=false``):
no ``Secure`` flag + ``SameSite=Lax`` — browsers reject
``Secure`` cookies over plain HTTP, and ``SameSite=None`` requires
``Secure``, so Lax is the correct same-origin fallback.
"""

from __future__ import annotations


def _samesite_of(set_cookie: str) -> str | None:
    for part in set_cookie.split(";"):
        part = part.strip()
        if part.lower().startswith("samesite="):
            return part.split("=", 1)[1].strip().lower()
    return None


def _has_secure_flag(set_cookie: str) -> bool:
    return any(p.strip().lower() == "secure" for p in set_cookie.split(";"))


def test_cookie_defaults_to_secure_samesite_none(monkeypatch) -> None:
    """Default keeps current production behavior: Secure + SameSite=None."""
    import os

    from starlette.responses import Response

    from app.api.v1.auth import _clear_token_cookie, _set_token_cookie
    from app.core.config import get_settings

    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().cookie_secure is True

        resp = Response()
        _set_token_cookie(resp, "tok")
        set_cookie = resp.headers.get("set-cookie", "")
        assert set_cookie, "No Set-Cookie header — _set_token_cookie did not fire"
        assert _has_secure_flag(set_cookie), f"Expected Secure flag. Got: {set_cookie}"
        assert _samesite_of(set_cookie) == "none", f"Expected SameSite=None. Got: {set_cookie}"

        clear_resp = Response()
        _clear_token_cookie(clear_resp)
        clear_cookie = clear_resp.headers.get("set-cookie", "")
        assert clear_cookie, "No Set-Cookie header on clear"
        assert _has_secure_flag(clear_cookie), f"Expected Secure flag on clear. Got: {clear_cookie}"
        assert _samesite_of(clear_cookie) == "none", (
            f"Expected SameSite=None on clear. Got: {clear_cookie}"
        )
    finally:
        get_settings.cache_clear()
        assert "COOKIE_SECURE" not in os.environ or True  # monkeypatch restores env


def test_cookie_secure_false_uses_lax_without_secure(monkeypatch) -> None:
    """COOKIE_SECURE=false → no Secure flag + SameSite=Lax (plain-HTTP LAN)."""
    from starlette.responses import Response

    from app.api.v1.auth import _clear_token_cookie, _set_token_cookie
    from app.core.config import get_settings

    monkeypatch.setenv("COOKIE_SECURE", "false")
    get_settings.cache_clear()
    try:
        assert get_settings().cookie_secure is False

        resp = Response()
        _set_token_cookie(resp, "tok")
        set_cookie = resp.headers.get("set-cookie", "")
        assert set_cookie, "No Set-Cookie header — _set_token_cookie did not fire"
        assert not _has_secure_flag(set_cookie), (
            f"Secure flag must be absent over plain HTTP. Got: {set_cookie}"
        )
        assert _samesite_of(set_cookie) == "lax", f"Expected SameSite=Lax. Got: {set_cookie}"

        clear_resp = Response()
        _clear_token_cookie(clear_resp)
        clear_cookie = clear_resp.headers.get("set-cookie", "")
        assert clear_cookie, "No Set-Cookie header on clear"
        assert not _has_secure_flag(clear_cookie), (
            f"Secure flag must be absent on clear over plain HTTP. Got: {clear_cookie}"
        )
        assert _samesite_of(clear_cookie) == "lax", (
            f"Expected SameSite=Lax on clear. Got: {clear_cookie}"
        )
    finally:
        get_settings.cache_clear()
