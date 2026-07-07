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

# Set Playwright browser install path (separate from system site-packages)
ENV PLAYWRIGHT_BROWSERS_PATH=/app/.playwright

# Install Python deps from pyproject.toml
COPY apps/api/pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -e ".[dev]"

# Install Playwright browsers (chromium + chromium-headless-shell)
RUN python -m playwright install chromium chromium-headless-shell --with-deps \
    && python -m playwright install --verify

# Copy application code
COPY apps/api/alembic.ini .
COPY apps/api/migrations ./migrations
COPY apps/api/app ./app

CMD ["sh", "-c", "alembic upgrade head 2>/dev/null; python -c 'from app.db.session import create_all; create_all()'; uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
