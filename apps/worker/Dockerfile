FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml .
COPY worker ./worker
RUN pip install --no-cache-dir -e .
CMD ["celery", "-A", "worker.app.celery_app", "worker", "--loglevel=info"]
