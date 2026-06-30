FROM python:3.12-slim

WORKDIR /app
COPY apps/worker/pyproject.toml .
# PR6: install the API package so worker.tasks.bootstrap can import
# app.db.seed, app.db.session, app.models. The whole apps/api tree
# must be copied (not just pyproject.toml) — setuptools with
# `tool.setuptools.packages.find` needs the actual `app/` source to
# build a wheel with the package. PR #19 only copied pyproject.toml,
# producing a 1.7KB empty wheel that caused `ModuleNotFoundError:
# No module named 'app'` on Render at Celery startup.
COPY apps/api ./apps/api
COPY apps/worker/worker ./worker
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir ./apps/api \
    && pip install --no-cache-dir .
RUN python -m playwright install --with-deps chromium
CMD ["celery", "-A", "worker.app.celery_app", "worker", "--loglevel=info"]
