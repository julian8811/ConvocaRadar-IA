"""Carga de snapshots sanitizados (JSON) y lector DB read-only opcional."""

from __future__ import annotations

import json
from pathlib import Path


def load_snapshot(path: str | Path) -> tuple[list[dict], dict[str, list[dict]], dict[str, list[dict]]]:
    """Lee {"sources": [...], "runs": [...], "opportunities": [...]}.

    Acepta runs/opps anidados por fuente o planos con source_id.
    Nunca escribe: solo parsea JSON local.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    sources = list(data.get("sources", []))
    runs_by: dict[str, list[dict]] = {}
    opps_by: dict[str, list[dict]] = {}

    def _put(bucket: dict[str, list[dict]], sid: str, item: dict) -> None:
        bucket.setdefault(sid, []).append(item)

    runs = data.get("runs", [])
    if isinstance(runs, dict):
        for sid, lst in runs.items():
            for r in lst or []:
                _put(runs_by, str(sid), r)
    else:
        for r in runs or []:
            _put(runs_by, str(r.get("source_id", "")), r)
    opps = data.get("opportunities", [])
    if isinstance(opps, dict):
        for sid, lst in opps.items():
            for o in lst or []:
                _put(opps_by, str(sid), o)
    else:
        for o in opps or []:
            _put(opps_by, str(o.get("source_id", "")), o)
    for s in sources:
        runs_by.setdefault(str(s.get("id")), [])
        opps_by.setdefault(str(s.get("id")), [])
    return sources, runs_by, opps_by


def load_readonly_db(session, *, limit: int | None = None,
                     source_key: str | None = None):
    """Snapshot read-only desde SQLAlchemy (SELECTs unicamente).

    No muta: no flush/commit, no toca last_run_at ni contadores.
    """
    from sqlalchemy import select

    from app.models import Opportunity, Source, SourceRun

    stmt = select(Source)
    if source_key:
        stmt = stmt.where(Source.key == source_key)
    if limit:
        stmt = stmt.limit(limit)
    sources = [dict(_row_to_dict(s)) for s in session.scalars(stmt).all()]
    runs_by: dict[str, list[dict]] = {}
    opps_by: dict[str, list[dict]] = {}
    for s in sources:
        sid = str(s["id"])
        runs = session.scalars(
            select(SourceRun).where(SourceRun.source_id == sid)
            .order_by(SourceRun.finished_at.desc()).limit(10)).all()
        runs_by[sid] = [dict(_row_to_dict(r)) for r in runs]
        opps = session.scalars(
            select(Opportunity).where(Opportunity.source_id == sid).limit(500)).all()
        opps_by[sid] = [dict(_row_to_dict(o)) for o in opps]
    return sources, runs_by, opps_by


def _row_to_dict(row) -> dict:
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}
