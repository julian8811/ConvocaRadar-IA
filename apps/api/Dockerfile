FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml .
COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && pip install --no-cache-dir .
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
