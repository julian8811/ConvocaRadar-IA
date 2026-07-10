"""Shared pytest fixtures for the API test suite.

The FastAPI app uses an in-memory rate limiter (``app.state.rate_limits``)
that is shared across all tests in the same process. Without intervention,
the bucket accumulates timestamps for every request and would eventually
hit the 120 req/min production limit, causing spurious 429s in tests
that run later in the session.

The ``autouse`` fixture below clears the bucket at the start of every
test so each test starts with an empty bucket. This keeps the suite
order-independent and avoids the rate limit polluting later tests.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock

# Test env defaults must be set before app imports — pydantic settings
# validate on first read and refuse to start without JWT_SECRET and
# INTERNAL_API_KEY. Per-file overrides (e.g. test_dashboard_health.py
# setting DATABASE_URL) take precedence because conftest only sets the
# shared, non-database settings.
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_convocaradar.db")
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("STORAGE_DIR", "./test_storage")
os.environ.setdefault("SMTP_HOST", "")
os.environ.setdefault("JWT_SECRET", "a" * 64)
os.environ.setdefault("RESET_TOKEN_SECRET", "b" * 64)
os.environ.setdefault("INTERNAL_API_KEY", "a" * 64)
os.environ.setdefault("BOOTSTRAP_SOURCES_ON_STARTUP", "false")
# In-process Celery (worker + beat) is started by the FastAPI lifespan
# in production. The test DB has no Redis broker, so the subprocess
# would fail and spam /tmp/celery-*.log with retry noise. Disable
# explicitly here so tests do not fork Celery children.
os.environ.setdefault("DISABLE_INPROCESS_CELERY", "1")

import pytest  # noqa: E402

import app.main as app_main  # noqa: E402
from app.core.rate_limit import email_login_limiter  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_rate_limit_bucket() -> None:
    """Clear the in-memory rate limit bucket before every test."""
    app_main.app.state.rate_limits.clear()
    email_login_limiter.clear()
    yield
    app_main.app.state.rate_limits.clear()
    email_login_limiter.clear()


@pytest.fixture
def connector_factory(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Return a factory that builds a mocked connector.

    The returned closure accepts ``(source_key, source_type, base_url,
    fixture_key)`` and returns a tuple ``(connector, mock_dict)``.

    ``mock_dict`` has keys ``fetch_httpx_text``, ``fetch_httpx_bytes``,
    ``render_page_html`` — the ``AsyncMock`` instances so tests can
    further customise them or inspect call counts.
    """

    import sys as _sys

    _factories: list[Any] = []

    def _build(
        source_key: str,
        *,
        source_type: str | None = None,
        base_url: str | None = "http://example.com",
        fixture_key: str | None = None,
    ) -> tuple[Any, dict[str, AsyncMock]]:
        from app.connectors.factory import connector_for
        from app.connectors import common as common_mod

        connector = connector_for(source_key, base_url, source_type)

        # Create fresh async mocks for this call
        mock_text = AsyncMock()
        mock_bytes = AsyncMock()
        mock_playwright = AsyncMock()

        # ── Save originals before patching ──────────────────────────────
        _orig_text = common_mod.fetch_httpx_text
        _orig_bytes = common_mod.fetch_httpx_bytes
        _orig_playwright = common_mod.render_page_html

        # ── Patch the canonical module ───────────────────────────────────
        monkeypatch.setattr(common_mod, "fetch_httpx_text", mock_text)
        monkeypatch.setattr(common_mod, "fetch_httpx_bytes", mock_bytes)
        monkeypatch.setattr(common_mod, "render_page_html", mock_playwright)

        # ── Patch every already-imported module whose references to
        #    common's functions may have been captured via direct import
        #    (e.g. ``from app.connectors.common import fetch_httpx_text``).
        #    Without this, the monkeypatch on ``common_mod`` is invisible
        #    to modules that already hold a local reference. ──────────────
        _aliases = [
            ("fetch_httpx_text", _orig_text, mock_text),
            ("fetch_httpx_bytes", _orig_bytes, mock_bytes),
            ("render_page_html", _orig_playwright, mock_playwright),
        ]
        for _mod_name, _mod in list(_sys.modules.items()):
            if _mod is common_mod or _mod is _build.__module__:
                continue
            for _func_name, _orig_func, _mock in _aliases:
                if getattr(_mod, _func_name, None) is _orig_func:
                    monkeypatch.setattr(_mod, _func_name, _mock)

        # Store references so tests can inspect them
        mocks = {
            "fetch_httpx_text": mock_text,
            "fetch_httpx_bytes": mock_bytes,
            "render_page_html": mock_playwright,
        }

        _factories.append((connector, mocks))
        return connector, mocks

    yield _build
