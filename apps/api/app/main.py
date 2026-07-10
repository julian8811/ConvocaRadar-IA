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
from app.connectors.health_check import check_playwright_binary, check_pypdf_import
from app.core.config import get_settings
from app.core.http_client import close_async_client, close_sync_client, http_client
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




async def _run_periodic_source_sweep(interval_seconds: int = 1800) -> None:
    """Every ``interval_seconds`` (default 30 min), trigger a sweep of all
    enabled sources. Redis is not reachable on the free tier, so we use
    an asyncio loop instead of the Celery beat schedule. The sweep runs
    inline (same process) using the existing ``execute_source_run_locally``
    codepath. Failures for individual sources are logged and skipped; a
    single bad source does not kill the sweep.

    As a side-effect, every ``WEEKLY_DIGEST_SECONDS`` (default 7 days) we
    also send the weekly digest for every org that has at least one
    organization. The digest is best-effort: a hard SMTP failure logs a
    warning and the loop keeps running.
    """
    from datetime import UTC, datetime

    WEEKLY_DIGEST_SECONDS = 604800  # 7 days
    last_digest_at: datetime | None = None

    await asyncio.sleep(30)  # let the API settle before the first sweep
    while True:
        try:
            from app.db.session import SessionLocal
            from app.models import Organization, Source
            from app.services import (
                execute_source_run_locally,
                send_weekly_digest,
                source_due_for_scraping,
            )
            from sqlalchemy import select

            db = SessionLocal()
            try:
                orgs = db.scalars(select(Organization)).all()
                if orgs:
                    sources = list(
                        db.scalars(
                            select(Source).where(Source.enabled.is_(True))
                        )
                    )
                    total = len(sources)
                    run_count = 0
                    for source in sources:
                        if not source_due_for_scraping(source):
                            continue
                        try:
                            execute_source_run_locally(db, source, organization_id=orgs[0].id)
                            run_count += 1
                        except Exception as exc:
                            db.rollback()
                            struct_logger.warning(
                                "sweep_source_failed",
                                source=source.key or source.id,
                                error=str(exc),
                            )
                    if run_count:
                        db.commit()
                    struct_logger.info(
                        "periodic_sweep_complete",
                        total=total,
                        due=run_count,
                    )

                    # Weekly digest. Fires at most once per process lifetime
                    # interval, so a long-running API instance stays under
                    # quota. Restarting the API restarts the timer — that's
                    # fine for a v1 cron substitute on Render's free tier.
                    now = datetime.now(UTC).replace(tzinfo=None)
                    if last_digest_at is None or (now - last_digest_at).total_seconds() >= WEEKLY_DIGEST_SECONDS:
                        delivered_count = 0
                        for org in orgs:
                            try:
                                if send_weekly_digest(db, org.id):
                                    delivered_count += 1
                            except Exception as exc:
                                struct_logger.warning(
                                    "weekly_digest_failed",
                                    organization_id=org.id,
                                    error=str(exc),
                                )
                        last_digest_at = now
                        struct_logger.info(
                            "weekly_digest_complete",
                            orgs=len(orgs),
                            delivered=delivered_count,
                        )
                else:
                    struct_logger.info("sweep_no_orgs")
            finally:
                db.close()
        except Exception as exc:
            struct_logger.warning("periodic_sweep_failed", error=str(exc))
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_all()
    ensure_bootstrap_data()

    # Run scraper infrastructure health checks (non-blocking, warnings only).
    # Both functions handle their own errors internally and return bool.
    check_playwright_binary()
    check_pypdf_import()

    # Pre-warm the shared HTTPX client singletons for connection pooling.
    # The call is lazy — it creates the client if not yet initialized.
    await http_client()

    # Background scheduler: every 30 minutes, run all enabled sources
    # via an asyncio loop instead of a Celery beat schedule.
    import asyncio
    scheduler_task = asyncio.create_task(_run_periodic_source_sweep())
    try:
        yield
    finally:
        scheduler_task.cancel()
        # Gracefully release pooled connections on shutdown.
        # close_sync_client is sync + blocking (TCP teardown); offload to
        # a thread so it doesn't block the async lifespan handler.
        import asyncio

        await close_async_client()
        await asyncio.to_thread(close_sync_client)


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
