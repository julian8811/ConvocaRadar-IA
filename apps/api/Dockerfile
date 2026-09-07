# syntax=docker/dockerfile:1.7
# ── Stage 1: install Python deps into /install prefix ────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

COPY apps/api/pyproject.toml ./
# The application itself is a local package; DL3013 version pinning applies to
# registry packages and is not meaningful for `.`. Dependency constraints live
# in pyproject.toml/uv.lock and are validated separately by CI.
# hadolint ignore=DL3013
RUN pip install --no-cache-dir --prefix=/install .

# ── Stage 2: runtime image ───────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Runtime system deps: libpq client + Playwright/Chromium headless libs.
# Pinning Debian package micro-versions would couple the build to one moving
# snapshot of python:3.12-slim. The base image tag is controlled and the image
# is rebuilt by CI, so deliberately exempt this apt transaction from DL3008.
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
        libcups2 libdrm2 libdbus-1-3 libxcb1 libxkbcommon0 libx11-6 \
        libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 \
        libgbm1 libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0 \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

# Browser binaries are installed at image-build time, never at container boot.
RUN playwright install chromium chromium-headless-shell

COPY apps/api/alembic.ini ./
COPY apps/api/migrations ./migrations
COPY apps/api/app ./app

RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --create-home --home-dir /home/app app \
    && mkdir -p /ms-playwright \
    && chown -R app:app /app /home/app /ms-playwright

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health/live', timeout=5)" || exit 1

# Alembic is the single source of truth for schema migrations. A healthy API
# therefore also proves migrations completed successfully before dependants run.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]