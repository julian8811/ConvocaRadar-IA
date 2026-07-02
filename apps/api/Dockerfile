FROM python:3.12-slim

WORKDIR /app

# Install only runtime deps for faster build
COPY apps/api/pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir fastapi uvicorn[standard] pydantic pydantic-settings \
        sqlalchemy alembic psycopg[binary] python-jose[cryptography] \
        python-multipart structlog httpx tenacity jinja2 \
        pgvector selectolax python-dateutil email-validator

# Copy application code
COPY apps/api/alembic.ini .
COPY apps/api/migrations ./migrations
COPY apps/api/app ./app
COPY apps/worker/worker ./worker

CMD ["sh", "-c", "alembic upgrade head 2>/dev/null; python -c 'from app.db.session import create_all; create_all()'; uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
