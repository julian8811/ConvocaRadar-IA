FROM python:3.12-slim

WORKDIR /app
COPY apps/worker/pyproject.toml .
# GAP-1 (dashboard-redesign): install the API package so worker.tasks.bootstrap
# can import app.db.seed, app.db.session, app.models. Without this, the new
# Celery task fails at import time in production.
COPY apps/api/pyproject.toml ./apps_api_pyproject.toml
COPY apps/worker/worker ./worker
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir ./apps_api_pyproject.toml \
    && pip install --no-cache-dir .
RUN python -m playwright install --with-deps chromium
CMD ["celery", "-A", "worker.app.celery_app", "worker", "--loglevel=info"]
