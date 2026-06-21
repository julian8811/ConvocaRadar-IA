FROM python:3.12-slim

WORKDIR /app
COPY apps/worker/pyproject.toml .
COPY apps/worker/worker ./worker
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && pip install --no-cache-dir .
RUN python -m playwright install --with-deps chromium
CMD ["python", "-m", "worker.entrypoint"]
