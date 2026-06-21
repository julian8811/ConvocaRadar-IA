FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .
COPY worker ./worker
CMD ["celery", "-A", "worker.app.celery_app", "worker", "--loglevel=info"]
