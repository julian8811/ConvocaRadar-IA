#!/usr/bin/env sh
# Playwright browsers location. The build installs them to the default
# Playwright path under /root/.cache/ms-playwright/. Render runtime may
# override PLAYWRIGHT_BROWSERS_PATH; we set it explicitly so Playwright
# can find the browsers regardless of Render's runtime environment.
# Tested paths:
#   /root/.cache/ms-playwright/  — default build-time install
#   /opt/render/.cache/ms-playwright/  — Render Docker build path
for _pw_cache in "/opt/render/.cache/ms-playwright" "/root/.cache/ms-playwright"; do
    if [ -d "$_pw_cache" ]; then
        export PLAYWRIGHT_BROWSERS_PATH="$_pw_cache"
        break
    fi
done
# Run Alembic migrations at startup (idempotent — only new ones apply)
alembic upgrade head 2>&1 || echo "Migration warning (non-fatal)"

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
