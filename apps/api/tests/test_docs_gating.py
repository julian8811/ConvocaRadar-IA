"""Docs-endpoint gating: API documentation must exist only in development.

The public API surface (Swagger UI at ``/docs``, ReDoc at ``/redoc`` and
the OpenAPI schema at ``/openapi.json``) reveals endpoint structure to
anyone who can reach the service. Outside development none of these may
be served, and because they are no longer in the rate-limit bypass set,
requests against them must still count toward the caller's bucket.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


@pytest.fixture
def app_for_env(monkeypatch: pytest.MonkeyPatch):
    """Rebuild ``app.main`` with ``APP_ENV`` set to the requested value.

    The FastAPI instance is constructed at import time from settings read
    once, so switching environments requires clearing the ``lru_cache``
    on ``get_settings`` and reloading the module. The teardown reloads
    once more with the environment restored so every other test keeps
    seeing the default development app.
    """
    import app.main as app_main  # noqa: F401  (import kept for reload symmetry)

    from app.core.config import get_settings

    def _build(app_env: str) -> TestClient:
        monkeypatch.setenv("APP_ENV", app_env)
        get_settings.cache_clear()
        return TestClient(importlib.reload(app_main).app)

    yield _build

    monkeypatch.undo()
    get_settings.cache_clear()
    importlib.reload(app_main)


def test_development_serves_all_docs_endpoints(app_for_env) -> None:
    client = app_for_env("development")
    for path in DOCS_PATHS:
        assert client.get(path).status_code == 200, path


def test_production_hides_all_docs_endpoints(app_for_env) -> None:
    client = app_for_env("production")
    for path in DOCS_PATHS:
        response = client.get(path)
        assert response.status_code == 404, f"{path} must not be served outside development"


def test_development_docs_request_counts_toward_rate_limit(app_for_env) -> None:
    import app.main as app_main

    client = app_for_env("development")
    bucket = app_main.app.state.rate_limits["testclient"]
    before = len(bucket)
    assert client.get("/docs").status_code == 200
    assert len(bucket) == before + 1, "docs requests must be counted where served"


def test_production_docs_request_counts_toward_rate_limit(app_for_env) -> None:
    import app.main as app_main

    client = app_for_env("production")
    bucket = app_main.app.state.rate_limits["testclient"]
    before = len(bucket)
    response = client.get("/docs")
    assert response.status_code == 404
    assert len(bucket) == before + 1, "gated docs requests must still consume budget"
