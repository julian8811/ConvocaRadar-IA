FROM python:3.12-slim

WORKDIR /app

# Copy application code
COPY apps/api .

# Install dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir fastapi uvicorn pydantic pydantic-settings \
        sqlalchemy psycopg2-binary httpx python-dateutil email-validator \
        alembic python-jose structlog pgvector

# Start server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
