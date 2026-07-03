#!/bin/bash
set -e

# Install Playwright Chromium browser if not already installed
python -c "
import subprocess, os, sys
cache_dir = '/opt/render/.cache'
browsers_path = os.path.join(cache_dir, 'ms-playwright')
if not os.path.isdir(browsers_path) or not os.listdir(browsers_path):
    print('[startup] Installing Playwright Chromium browser...')
    sys.stdout.flush()
    env = os.environ.copy()
    env['PLAYWRIGHT_BROWSERS_PATH'] = cache_dir
    result = subprocess.run(
        [sys.executable, '-m', 'playwright', 'install', 'chromium'],
        env=env,
        capture_output=True, text=True, timeout=180
    )
    if result.returncode != 0:
        print(f'[startup] Playwright install stdout: {result.stdout[-200:]}')
        print(f'[startup] Playwright install stderr: {result.stderr[-200:]}')
    else:
        print('[startup] Chromium installed successfully')
else:
    print(f'[startup] Chromium already installed at {browsers_path}')
sys.stdout.flush()
"

# Start the application
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
