from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from collections import defaultdict, deque
import logging
import os
import subprocess
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


# In-process Celery worker + beat. Render's free plan does not allow
# background workers, so we run the Celery worker as a child process
# inside the API container. Both share the same Python interpreter
# and the same Redis broker; the worker picks up tasks enqueued by
# the API (e.g. seed_default_sources_for_org on register). beat
# schedules the periodic 30-min scrape + 5-min alert sweep.
_INPROCESS_CELERY_WORKER: subprocess.Popen | None = None
_INPROCESS_CELERY_BEAT: subprocess.Popen | None = None


def _start_inprocess_celery() -> None:
    """Spawn Celery worker + beat as detached subprocesses.

    Failures are non-fatal: the API must keep starting even if Redis
    is unreachable, because bootstrap.py will retry there too. Logs go
    to /tmp/celery-{worker,beat}.log so they show up in Render's
    "Logs" tab alongside the API's stdout.
    """
    global _INPROCESS_CELERY_WORKER, _INPROCESS_CELERY_BEAT
    if os.getenv("DISABLE_INPROCESS_CELERY") == "1":
        return
    common = ["celery", "-A", "worker.app.celery_app", "--loglevel=info"]
    try:
        _INPROCESS_CELERY_WORKER = subprocess.Popen(
            common + ["worker"],
            stdout=open("/tmp/celery-worker.log", "ab"),
            stderr=subprocess.STDOUT,
        )
        struct_logger.info("inprocess_celery_worker_started", pid=_INPROCESS_CELERY_WORKER.pid)
    except Exception as exc:  # pragma: no cover - defensive
        struct_logger.warning("inprocess_celery_worker_start_failed", error=str(exc))
    try:
        _INPROCESS_CELERY_BEAT = subprocess.Popen(
            common + ["beat"],
            stdout=open("/tmp/celery-beat.log", "ab"),
            stderr=subprocess.STDOUT,
        )
        struct_logger.info("inprocess_celery_beat_started", pid=_INPROCESS_CELERY_BEAT.pid)
    except Exception as exc:  # pragma: no cover - defensive
        struct_logger.warning("inprocess_celery_beat_start_failed", error=str(exc))


def _stop_inprocess_celery() -> None:
    """Terminate the worker + beat subprocesses on API shutdown."""
    for proc, name in [
        (_INPROCESS_CELERY_WORKER, "celery_worker"),
        (_INPROCESS_CELERY_BEAT, "celery_beat"),
    ]:
        if proc is None or proc.poll() is not None:
            continue
        try:
            proc.terminate()
            proc.wait(timeout=10)
            struct_logger.info("inprocess_celery_stopped", component=name, pid=proc.pid)
        except subprocess.TimeoutExpired:
            proc.kill()
            struct_logger.warning("inprocess_celery_killed_after_timeout", component=name)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_all()
    ensure_bootstrap_data()
    _start_inprocess_celery()
    try:
        yield
    finally:
        _stop_inprocess_celery()


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
    # Bypass rate limiting for liveness/readiness probes and the internal
    # scheduler endpoints. Orchestrators (k8s, Render) and the scheduler may
    # legitimately call these endpoints at high frequency.
    if path in {
        "/health",
        "/api/v1/health",
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/docs",
        "/openapi.json",
    } or path.startswith("/api/v1/internal/"):
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


# Security headers middleware. Runs after every response so headers are
# present even when an exception handler short-circuits the other middleware.
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    # CSP: allow the Vercel frontend, Cloudflare analytics, and inline scripts
    # needed by React and Recharts. Default-src 'self' for everything else.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://convocaradar-web.vercel.app; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "connect-src 'self' https://convocaradar-api.onrender.com; "
        "frame-ancestors 'none'"
    )
    return response


@app.get("/health")
def health() -> dict[str, str]:
    """Unversioned liveness probe. Returns 200 as long as the process is up."""
    return {"status": "ok", "service": "convocaradar-api"}


def _check_database() -> bool:
    """Run a trivial SELECT against the engine. Returns True on success."""
    from sqlalchemy import text

    from app.db.session import engine

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return True


def _readiness_response() -> JSONResponse:
    """Build the readiness response — 200 when DB is reachable, 503 otherwise."""
    try:
        if _check_database():
            return JSONResponse(
                status_code=200,
                content={"status": "ok", "database": "reachable"},
            )
    except SQLAlchemyError:
        struct_logger.warning("healthcheck_db_unreachable")
    return JSONResponse(
        status_code=503,
        content={"status": "degraded", "database": "unreachable"},
    )


@app.get("/api/v1/health")
def health_v1() -> JSONResponse:
    """Readiness probe with a database connectivity check.

    Use this for k8s readinessProbe and the Render healthCheckPath: when the
    DB is down, we want the orchestrator to stop routing traffic to this
    instance until it recovers. The body shape is stable so existing
    monitoring keeps working.
    """
    return _readiness_response()


@app.get("/api/v1/health/live")
def health_v1_live() -> dict[str, str]:
    """Liveness probe — 200 as long as the process is up.

    Does NOT touch the database. Use this for k8s livenessProbe: a process
    that can answer this endpoint is alive; the orchestrator should not kill
    it just because Postgres is having a bad day.
    """
    return health()


@app.get("/api/v1/health/ready")
def health_v1_ready() -> JSONResponse:
    """Alias for /api/v1/health with explicit 'ready' naming for k8s."""
    return _readiness_response()


app.include_router(api_router)
