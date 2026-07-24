"""Dedicated scheduler process for source sweeps and digests."""
import asyncio
import threading
import time
from pathlib import Path

from app.main import _run_periodic_source_sweep

HEARTBEAT = Path("/tmp/convocaradar-worker.heartbeat")

def _heartbeat() -> None:
    while True:
        HEARTBEAT.touch()
        time.sleep(15)

def main() -> None:
    thread = threading.Thread(target=_heartbeat, daemon=True)
    thread.start()
    asyncio.run(_run_periodic_source_sweep())

if __name__ == "__main__":
    main()
