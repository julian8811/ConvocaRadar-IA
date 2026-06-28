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
os.environ.setdefault("INTERNAL_API_KEY", "a" * 64)
os.environ.setdefault("BOOTSTRAP_SOURCES_ON_STARTUP", "false")
# In-process Celery (worker + beat) is started by the FastAPI lifespan
# in production. The test DB has no Redis broker, so the subprocess
# would fail and spam /tmp/celery-*.log with retry noise. Disable
# explicitly here so tests do not fork Celery children.
os.environ.setdefault("DISABLE_INPROCESS_CELERY", "1")

import pytest  # noqa: E402

import app.main as app_main  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_rate_limit_bucket() -> None:
    """Clear the in-memory rate limit bucket before every test."""
    app_main.app.state.rate_limits.clear()
    yield
    app_main.app.state.rate_limits.clear()
