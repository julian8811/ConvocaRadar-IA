from __future__ import annotations

import os
import signal
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path not in {"/", "/health"}:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def main() -> None:
    port = int(os.getenv("PORT", "10000"))
    worker = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "worker.app.celery_app",
            "worker",
            "--loglevel=info",
        ]
    )
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)

    def _shutdown(*_: object) -> None:
        if server:
            server.shutdown()
        if worker.poll() is None:
            worker.terminate()
            try:
                worker.wait(timeout=20)
            except subprocess.TimeoutExpired:
                worker.kill()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        server.serve_forever()
    finally:
        _shutdown()
        if worker.poll() is None:
            worker.wait()


if __name__ == "__main__":
    main()
