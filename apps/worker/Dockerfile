FROM python:3.12-slim

WORKDIR /app

# Install system deps for psycopg
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install the API package first (editable) so the worker can import app.*
COPY apps/api/pyproject.toml apps/api/
COPY apps/api/app apps/api/app
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -e apps/api

# Install worker package (editable)
COPY apps/worker/pyproject.toml apps/worker/
COPY apps/worker/worker apps/worker/worker
RUN pip install --no-cache-dir -e apps/worker

# Run Arq worker
CMD ["python", "-m", "arq", "worker.main.WorkerSettings"]
