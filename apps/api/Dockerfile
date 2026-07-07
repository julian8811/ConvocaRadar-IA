FROM python:3.12-slim

WORKDIR /app

# Install system deps for Playwright and psycopg
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 libxcb1 libxkbcommon0 libx11-6 \
    libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps from pyproject.toml
COPY apps/api/pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -e ".[dev]"

# Install Playwright browsers to Render-compatible path.
# Render runtime sets PLAYWRIGHT_BROWSERS_PATH or HOME to /opt/render/,
# so Playwright looks for browsers under /opt/render/.cache/ms-playwright/.
# We install there during build so browsers are found at runtime.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/render/.cache/ms-playwright
RUN mkdir -p /opt/render/.cache && \
    python -m playwright install chromium chromium-headless-shell --with-deps && \
    python -m playwright install --verify

# Copy application code
COPY apps/api/alembic.ini .
COPY apps/api/migrations ./migrations
COPY apps/api/app ./app

# Runtime: ensure Playwright browsers are available at Render's expected path
# (fallback in case Render overrides the build-time ENV)
CMD ["sh", "-c", "\
  if [ -n \"$PLAYWRIGHT_BROWSERS_PATH\" ] && [ \"$PLAYWRIGHT_BROWSERS_PATH\" != '/opt/render/.cache/ms-playwright' ] && [ -d /opt/render/.cache/ms-playwright ]; then \
    mkdir -p \"$(dirname \"$PLAYWRIGHT_BROWSERS_PATH\")\" && \
    ln -sf /opt/render/.cache/ms-playwright \"$PLAYWRIGHT_BROWSERS_PATH\" 2>/dev/null || true; \
  fi; \
  alembic upgrade head 2>/dev/null; \
  python -c 'from app.db.session import create_all; create_all()'; \
  uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} \
"]
