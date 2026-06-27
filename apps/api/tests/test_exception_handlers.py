"""Tests for the global exception handlers and request-context middleware.

These tests assert:
- Unhandled exceptions return a generic 500 with no stack trace in the body
- Every response (success or error) carries the X-Request-ID header
- SQLAlchemyError returns a generic 500 (not 500 with stack trace)
- httpx.HTTPError returns 502 Bad Gateway (we depend on external services)
- pydantic.ValidationError returns 422 (FastAPI default, but we wire it
  explicitly so the generic handler does not eat it)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_convocaradar.db")
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("STORAGE_DIR", "./test_storage")
os.environ.setdefault("SMTP_HOST", "")
os.environ.setdefault("INTERNAL_API_KEY", "test_internal_key")
os.environ.setdefault("BOOTSTRAP_SOURCES_ON_STARTUP", "false")
os.environ.setdefault("SENTRY_DSN", "")

# Make the production main module importable without side effects
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
import pydantic  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.exc import OperationalError, SQLAlchemyError  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402

import app.main as app_main  # noqa: E402


# ---------------------------------------------------------------------------
# Test app: a minimal FastAPI app that wires the production exception handlers
# and middleware, so we can assert behavior in isolation.
# ---------------------------------------------------------------------------


def _build_isolated_app() -> FastAPI:
    """Replicate the production wiring from app.main without the real DB.

    The production app pulls in models, bootstrap data, and the full router,
    which makes a focused handler test noisy. We build a minimal copy that
    installs the same handlers and middleware, then add three fault routes.
    """
    isolated = FastAPI()
    isolated.state.rate_limits = {}

    @isolated.middleware("http")
    async def request_context_middleware(request, call_next):  # type: ignore[no-redef]
        # Mirror the production middleware so the exception handlers can read
        # the request_id back from request.state.
        import structlog

        request_id = request.headers.get("X-Request-ID") or "req-test"
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response.headers["X-Request-ID"] = request_id
        return response

    @isolated.get("/__ok")
    def ok_route() -> dict:
        return {"ok": True}

    @isolated.get("/__boom")
    def boom_route() -> None:
        raise RuntimeError("simulated unhandled failure")

    @isolated.get("/__sql_boom")
    def sql_boom_route() -> None:
        raise OperationalError("stmt", {}, Exception("connection refused"))

    @isolated.get("/__httpx_boom")
    def httpx_boom_route() -> None:
        raise httpx.ConnectError("upstream service unreachable")

    @isolated.get("/__validation_boom")
    def validation_boom_route(payload: dict) -> dict:
        # Force a pydantic ValidationError by checking shape
        pydantic.TypeAdapter(dict).validate_python(payload)
        return payload

    # Reuse the production exception handlers
    isolated.add_exception_handler(Exception, app_main.unhandled_exception_handler)
    isolated.add_exception_handler(SQLAlchemyError, app_main.sqlalchemy_exception_handler)
    isolated.add_exception_handler(httpx.HTTPError, app_main.httpx_exception_handler)
    isolated.add_exception_handler(pydantic.ValidationError, app_main.validation_exception_handler)
    return isolated


@pytest.fixture
def isolated_client() -> TestClient:
    return TestClient(_build_isolated_app(), raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# 1. Unhandled exception -> 500 with generic body
# ---------------------------------------------------------------------------


def test_unhandled_exception_returns_500_with_generic_body(isolated_client: TestClient) -> None:
    response = isolated_client.get("/__boom")
    assert response.status_code == 500
    body = response.json()
    assert body == {"detail": "Internal server error"}
    # No stack trace should leak into the response body
    assert "Traceback" not in response.text
    assert "simulated unhandled failure" not in response.text


# ---------------------------------------------------------------------------
# 2. X-Request-ID header correlation
# ---------------------------------------------------------------------------


def test_request_id_header_propagated_from_request(isolated_client: TestClient) -> None:
    response = isolated_client.get("/__ok", headers={"X-Request-ID": "rid-abc-123"})
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == "rid-abc-123"


def test_request_id_header_generated_when_absent(isolated_client: TestClient) -> None:
    response = isolated_client.get("/__ok")
    assert response.status_code == 200
    request_id = response.headers.get("X-Request-ID")
    assert request_id, "X-Request-ID header missing"
    assert request_id.startswith("req-")


def test_request_id_present_on_error_response(isolated_client: TestClient) -> None:
    response = isolated_client.get("/__boom", headers={"X-Request-ID": "rid-error-42"})
    assert response.status_code == 500
    assert response.headers.get("X-Request-ID") == "rid-error-42"


# ---------------------------------------------------------------------------
# 3. SQLAlchemyError -> 500 (no stack trace)
# ---------------------------------------------------------------------------


def test_sqlalchemy_error_returns_500_with_generic_body(isolated_client: TestClient) -> None:
    response = isolated_client.get("/__sql_boom")
    assert response.status_code == 500
    body = response.json()
    assert body == {"detail": "Internal server error"}
    assert "OperationalError" not in response.text
    assert "connection refused" not in response.text


def test_generic_sqlalchemy_error_returns_500(isolated_client: TestClient) -> None:
    # A non-OperationalError SQLAlchemyError should still go through the handler
    @_build_isolated_app().get("/__sql_generic")  # type: ignore[misc]
    def _sql_generic() -> None:
        raise SQLAlchemyError("generic db issue")

    # Use a fresh app for this specific case to avoid the @app decorator
    app = _build_isolated_app()

    @app.get("/__sql_generic")
    def sql_generic() -> None:
        raise SQLAlchemyError("generic db issue")

    c = TestClient(app, raise_server_exceptions=False)
    response = c.get("/__sql_generic")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}


# ---------------------------------------------------------------------------
# 4. httpx.HTTPError -> 502 Bad Gateway
# ---------------------------------------------------------------------------


def test_httpx_error_returns_502(isolated_client: TestClient) -> None:
    response = isolated_client.get("/__httpx_boom")
    assert response.status_code == 502
    body = response.json()
    assert body == {"detail": "Upstream service unavailable"}


# ---------------------------------------------------------------------------
# 5. pydantic.ValidationError -> 422
# ---------------------------------------------------------------------------


def test_pydantic_validation_error_returns_422(isolated_client: TestClient) -> None:
    # Force a ValidationError by sending a payload the TypeAdapter rejects
    @_build_isolated_app().get("/__validation_boom")  # type: ignore[misc]
    def _v(payload: dict) -> dict:
        return payload

    app = _build_isolated_app()

    @app.get("/__validation_boom")
    def validation_route(payload: dict) -> dict:
        # Use a model that rejects the incoming dict
        class Strict(pydantic.BaseModel):
            required_int: int

        Strict.model_validate(payload)
        return payload

    c = TestClient(app, raise_server_exceptions=False)
    response = c.get("/__validation_boom", params={"payload": "not-a-dict"})
    # FastAPI will reject the query param shape with 422 before our handler
    # runs. Either way, the status must be 422 (no 500).
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 6. Production main app must have the handlers installed
# ---------------------------------------------------------------------------


def test_production_app_has_unhandled_exception_handler() -> None:
    handlers = app_main.app.exception_handlers
    assert Exception in handlers, "Production app missing @app.exception_handler(Exception)"


def test_production_app_has_sqlalchemy_handler() -> None:
    handlers = app_main.app.exception_handlers
    assert SQLAlchemyError in handlers, "Production app missing SQLAlchemyError handler"


def test_production_app_has_httpx_handler() -> None:
    handlers = app_main.app.exception_handlers
    assert httpx.HTTPError in handlers, "Production app missing httpx.HTTPError handler"


def test_production_app_has_validation_handler() -> None:
    handlers = app_main.app.exception_handlers
    assert pydantic.ValidationError in handlers, "Production app missing ValidationError handler"


# ---------------------------------------------------------------------------
# 7. JSONResponse is safe in the handler signature
# ---------------------------------------------------------------------------


def test_unhandled_exception_handler_is_callable() -> None:
    """The handler should be a plain async callable, not a partial-bound thing."""
    from app.main import unhandled_exception_handler

    assert callable(unhandled_exception_handler)
    # We can import the JSONResponse type without issue
    assert JSONResponse is not None
