FROM python:3.12-slim

WORKDIR /app
COPY apps/api/pyproject.toml .
COPY apps/api/alembic.ini .
COPY apps/api/migrations ./migrations
COPY apps/api/app ./app
COPY apps/worker/worker ./worker
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && pip install --no-cache-dir .
RUN python -m playwright install --with-deps chromium
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
