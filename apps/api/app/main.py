from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from collections import defaultdict, deque
import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.bootstrap import ensure_bootstrap_data
from app.db.session import create_all

configure_logging()
settings = get_settings()
logger = logging.getLogger(__name__)

if settings.sentry_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration

        sentry_sdk.init(dsn=settings.sentry_dsn, integrations=[FastApiIntegration()], traces_sample_rate=0.1)
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
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


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
