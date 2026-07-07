#!/usr/bin/env sh
# Create Playwright browsers symlink if needed at Render runtime.
# Render sets PLAYWRIGHT_BROWSERS_PATH to /opt/render/.cache/ms-playwright
# but Playwright installs to ~/.cache/ms-playwright during build.
PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-}"
HOME_CACHE="${HOME:-/tmp}/.cache/ms-playwright"
if [ -n "$PLAYWRIGHT_BROWSERS_PATH" ] && [ "$PLAYWRIGHT_BROWSERS_PATH" != "$HOME_CACHE" ] && [ -d "$HOME_CACHE" ]; then
    mkdir -p "$(dirname "$PLAYWRIGHT_BROWSERS_PATH")" 2>/dev/null
    ln -sf "$HOME_CACHE" "$PLAYWRIGHT_BROWSERS_PATH" 2>/dev/null || true
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
