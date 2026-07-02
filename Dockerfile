FROM python:3.12-slim

WORKDIR /app

# Copy ALL application code first
COPY apps/api/pyproject.toml .
COPY apps/api/alembic.ini .
COPY apps/api/migrations ./migrations
COPY apps/api/app ./app
COPY apps/worker/worker ./worker

# Install dependencies (pyproject.toml has all deps)
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir .

# Start server (alembic + create_all + uvicorn)
CMD ["sh", "-c", "alembic upgrade head 2>/dev/null; python -c 'from app.db.session import create_all; create_all()' 2>/dev/null; uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
