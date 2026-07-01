"""Run the Celery worker alongside a minimal health-check HTTP server.

Render requires every web/worker service to respond to a configured
health check path (default: /health). The Celery worker does not serve
HTTP, so we embed a tiny HTTP server that just returns 200 OK —
Render checks the health endpoint, requests transparently reach the
same container, and the main process runs the Celery worker.
"""

import http.server
import json
import os
import subprocess
import sys
import threading


PORT = int(os.environ.get("PORT", 10000))
HEALTH_PATH = os.environ.get("HEALTH_CHECK_PATH", "/health")


class HealthHandler(http.server.BaseHTTPRequestHandler):
    """Minimal health check — always responds 200."""

    def do_GET(self):  # noqa: N802
        if self.path == HEALTH_PATH:
            self._ok()
        else:
            self._not_found()

    def _ok(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        body = json.dumps({"status": "ok", "service": "convotracker-worker"}).encode()
        self.wfile.write(body)

    def _not_found(self):
        self.send_response(404)
        self.end_headers()

    # Suppress default request logging to stderr.
    def log_message(self, format, *args):  # noqa: N802
        pass


def start_health_server() -> threading.Thread:
    server = http.server.HTTPServer(("0.0.0.0", PORT), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def main() -> int:
    # Let Render's health check bind before the worker starts.
    start_health_server()
    # Run the Celery worker in the foreground (so signals propagate).
    cmd = [
        sys.executable,
        "-m",
        "celery",
        "-A",
        "worker.app.celery_app",
        "worker",
        "--loglevel=info",
    ]
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
