#!/usr/bin/env sh
# Playwright browsers were downloaded to /opt/render/.cache/ during build
# (that's where PLAYWRIGHT_BROWSERS_PATH pointed at build time).
# Render runtime overrides PLAYWRIGHT_BROWSERS_PATH to
# /opt/render/.cache/ms-playwright, causing "Executable doesn't exist".
# Override it back so Playwright finds the browsers.
export PLAYWRIGHT_BROWSERS_PATH="/opt/render/.cache"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
