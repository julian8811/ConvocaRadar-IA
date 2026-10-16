"""Explicit CORS + settings-derived CSP (T3 seguridad-remediacion).

Contract:
- CORS preflight from an allowed origin returns exactly the configured
  methods/headers — never ``*``.
- The Content-Security-Policy is derived from settings (FRONTEND_URL /
  BACKEND_URL hosts), never hardcoded cloud domains (vercel.app,
  onrender.com).

RED tests: the preflight currently echoes ``*``-style broad values and
the CSP contains hardcoded cloud domains.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_cors_preflight_returns_explicit_methods_and_headers() -> None:
    """OPTIONS preflight must list explicit methods/headers, never '*'."""
    from app.db.seed import seed
    from app.main import app

    seed()
    c = TestClient(app)
    r = c.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "http://localhost:3002",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type, x-csrf-protection",
        },
    )
    assert r.status_code == 200, f"Expected preflight 200, got {r.status_code}."
    methods = r.headers.get("access-control-allow-methods", "")
    headers = r.headers.get("access-control-allow-headers", "")
    assert "*" not in methods, f"Preflight methods must be explicit, got {methods!r}."
    assert "*" not in headers, f"Preflight headers must be explicit, got {headers!r}."
    for token in ("POST", "GET", "DELETE"):
        assert token in methods, f"Expected {token} in {methods!r}."
    for token in ("content-type", "x-csrf-protection"):
        assert token in headers.lower(), f"Expected {token} in {headers!r}."


def test_csp_is_derived_from_settings_not_hardcoded_cloud() -> None:
    """CSP must reflect settings hosts, never hardcoded vercel/render domains."""
    from app.db.seed import seed
    from app.main import app

    seed()
    c = TestClient(app)
    r = c.get("/api/v1/health/live")
    assert r.status_code == 200
    csp = r.headers.get("content-security-policy", "")
    assert csp, "Expected a Content-Security-Policy header on API responses."
    assert "vercel.app" not in csp, f"CSP must not hardcode cloud domains: {csp!r}."
    assert "onrender.com" not in csp, f"CSP must not hardcode cloud domains: {csp!r}."
    assert "frame-ancestors 'none'" in csp, f"CSP lost frame-ancestors 'none': {csp!r}."
