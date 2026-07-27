# syntax=docker/dockerfile:1.7
# ── Stage 1: install Python deps into /install prefix ────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# pip + setuptools upgrade only (no build-essential needed: psycopg[binary] ships
# pre-built wheels and the rest of the stack is pure-Python with wheels too).
RUN pip install --no-cache-dir --upgrade pip

COPY apps/api/pyproject.toml ./
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
# (Build tools, headers, and dev libs were only needed in the builder stage.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
        libcups2 libdrm2 libdbus-1-3 libxcb1 libxkbcommon0 libx11-6 \
        libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 \
        libgbm1 libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0 \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Install Playwright Chromium into the runtime layer (browsers land in /ms-playwright,
# which is the value of $PLAYWRIGHT_BROWSERS_PATH set above).
RUN playwright install chromium chromium-headless-shell

# Application code
COPY apps/api/alembic.ini ./
COPY apps/api/migrations ./migrations
COPY apps/api/app ./app

# Non-root runtime user. Playwright cache is owned by app so the user can read
# browsers without needing root at runtime.
RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --create-home --home-dir /home/app app \
    && mkdir -p /ms-playwright \
    && chown -R app:app /app /home/app /ms-playwright

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health/live', timeout=5)" || exit 1

# Single source of truth for schema: Alembic. We do NOT call create_all() here —
# the previous double-migration (alembic + create_all) could drift between
# environments. See audit note 2026-07.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
