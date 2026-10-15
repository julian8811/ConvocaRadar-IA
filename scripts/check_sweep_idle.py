#!/usr/bin/env python3
"""Pre-deploy guard: refuse to rebuild while a source sweep is active.

Contexto: los sweeps corren en un daemon thread dentro del contenedor api;
recrear el contenedor a mitad de un sweep lo marca failed con conteos
parciales (incidente 2026-10-15: dos sweeps muertos por rebuilds). Este
check corre ANTES de cada rebuild en el servidor:

    docker compose -f docker-compose.server.yml exec -T api python - < scripts/check_sweep_idle.py

Exit codes: 0 idle (o sólo tareas rancias >6h, se reportan), 1 hay un sweep
activo (no hacer rebuild).
"""

from __future__ import annotations

import datetime as _dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apps", "api"))

ACTIVE_WINDOW_HOURS = 6


def main() -> int:
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import Task

    cutoff = _dt.datetime.now() - _dt.timedelta(hours=ACTIVE_WINDOW_HOURS)
    with SessionLocal() as db:
        unfinished = list(
            db.scalars(
                select(Task)
                .where(Task.task_type == "source_sweep", Task.finished_at.is_(None))
                .order_by(Task.started_at.desc().nullslast())
            )
        )
    active = [t for t in unfinished if t.started_at is not None and t.started_at >= cutoff]
    stale = [t for t in unfinished if t not in active]
    for t in active:
        print(
            "ACTIVE sweep id=%s status=%s started=%s"
            % (t.id, t.status, t.started_at)
        )
    for t in stale:
        print(
            "STALE unfinished sweep id=%s status=%s started=%s (no bloquea)"
            % (t.id, t.status, t.started_at)
        )
    if active:
        print("BLOCKED: hay %d sweep(s) activo(s); no hacer rebuild" % len(active))
        return 1
    print("IDLE: sin sweeps activos; rebuild permitido")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
