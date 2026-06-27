from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from collections import defaultdict, deque
import logging
import time

import httpx
import pydantic
import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.bootstrap import ensure_bootstrap_data
from app.db.session import create_all

configure_logging()
settings = get_settings()
logger = logging.getLogger(__name__)
struct_logger = structlog.get_logger(__name__)

if settings.sentry_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration

        # PII off by default — ConvocaRadar is a B2B tool for funding teams;
        # we do not want tokens, emails, or opportunity text flowing into Sentry.
        # Set SENTRY_SEND_DEFAULT_PII=true in env to opt in if needed.
        send_pii = bool(getattr(settings, "sentry_send_default_pii", False))
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            integrations=[FastApiIntegration()],
            traces_sample_rate=0.1,
            send_default_pii=send_pii,
        )
    except ImportError:
        logger.warning("Sentry DSN configured but sentry-sdk is not installed")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_all()
    ensure_bootstrap_data()
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.state.rate_limits = defaultdict(deque)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or f"req-{int(time.time() * 1000)}"
    # Stash on request.state so exception handlers can read it even when the
    # structlog contextvars are cleared by the time they run.
    request.state.request_id = request_id
    # Bind the request_id into structlog contextvars so every log line emitted
    # while handling this request carries the correlation id without having to
    # pass it around manually.
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


# ---------------------------------------------------------------------------
# Global exception handlers
#
# Order matters: FastAPI matches handlers by MRO, so the more specific ones
# (SQLAlchemyError, httpx.HTTPError, pydantic.ValidationError) are registered
# AFTER the catch-all Exception handler would catch them. The
# @app.exception_handler decorator registers in reverse, so we register the
# specific handlers FIRST and the generic one last to keep specificity ordering
# correct.
# ---------------------------------------------------------------------------


async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    struct_logger.exception(
        "sqlalchemy_error",
        error_type=type(exc).__name__,
    )
    return _error_response(
        request=request,
        status_code=500,
        detail="Internal server error",
    )


async def httpx_exception_handler(request: Request, exc: httpx.HTTPError) -> JSONResponse:
    struct_logger.warning(
        "upstream_http_error",
        error_type=type(exc).__name__,
        error_message=str(exc),
    )
    return _error_response(
        request=request,
        status_code=502,
        detail="Upstream service unavailable",
    )


async def validation_exception_handler(
    request: Request, exc: pydantic.ValidationError
) -> JSONResponse:
    # Mirror FastAPI's default shape so existing clients keep working.
    return _error_response(
        request=request,
        status_code=422,
        detail=exc.errors(),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    struct_logger.exception(
        "unhandled_exception",
        error_type=type(exc).__name__,
    )
    return _error_response(
        request=request,
        status_code=500,
        detail="Internal server error",
    )


def _error_response(*, request: Request, status_code: int, detail) -> JSONResponse:
    """Build an error JSONResponse with the X-Request-ID header stamped on it.

    Exception handlers return a response that the request_context_middleware
    never sees (the exception bypasses the middleware's response path), so we
    have to stamp the X-Request-ID here. We read it from request.state where
    the middleware stashed it; structlog contextvars would also work but are
    cleared by the middleware's `finally` block before the handler runs.
    """
    request_id = getattr(request.state, "request_id", None)
    headers = {"X-Request-ID": request_id} if request_id else None
    return JSONResponse(status_code=status_code, content={"detail": detail}, headers=headers)


# Specific handlers register before the catch-all so FastAPI can match by MRO
# (the most specific class wins).
app.add_exception_handler(SQLAlchemyError, sqlalchemy_exception_handler)
app.add_exception_handler(httpx.HTTPError, httpx_exception_handler)
app.add_exception_handler(pydantic.ValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    path = request.url.path
    if path in {"/health", "/docs", "/openapi.json"} or path.startswith("/api/v1/internal/"):
        return await call_next(request)
    client_host = (request.client.host if request.client else "unknown") or "unknown"
    bucket = app.state.rate_limits[client_host]
    now = time.monotonic()
    window = settings.rate_limit_window_seconds
    limit = settings.rate_limit_requests_per_minute
    while bucket and now - bucket[0] > window:
        bucket.popleft()
    if len(bucket) >= limit:
        retry_after = max(window - (now - bucket[0]), 1) if bucket else window
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests"},
            headers={"Retry-After": str(int(retry_after))},
        )
    bucket.append(now)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.frontend_url,
        "https://convocaradar-web.vercel.app",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:3004",
        "http://127.0.0.1:3004",
        "http://localhost:3006",
        "http://127.0.0.1:3006",
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "convocaradar-api"}


@app.get("/api/v1/health")
def health_v1() -> dict[str, str]:
    return health()


app.include_router(api_router)
