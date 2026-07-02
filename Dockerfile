FROM python:3.12-slim

WORKDIR /app
COPY apps/api/pyproject.toml .
COPY apps/api/alembic.ini .
COPY apps/api/migrations ./migrations
COPY apps/api/app ./app
COPY apps/worker/worker ./worker
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && pip install --no-cache-dir .
# Playwright browsers omitted for Render Free tier (build timeout / 300MB).
# The httpx fallback handles sources that would need JS rendering.
# RUN python -m playwright install --with-deps chromium

# Startup sequence:
#   1. Try `alembic upgrade head` (works on a fresh DB where the schema
#      has not been initialized yet)
#   2. Always run `create_all()` from app.db.session — it is idempotent
#      and only creates tables that are missing, so it is safe to run
#      on a DB that already has the schema (where alembic would fail
#      with "relation already exists")
#   3. Start uvicorn. The FastAPI lifespan calls create_all() again
#      defensively on every startup.
CMD ["sh", "-c", "alembic upgrade head 2>/dev/null; python -c 'from app.db.session import create_all; create_all()'; uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
