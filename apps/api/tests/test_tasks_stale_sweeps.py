"""Stale sweep marker must not murder live sweeps.

Bug 2026-10-15: tres barridos (10:29, 11:07, 14:06) murieron justo a los
~10 min con conteos parciales (51, 14, 150). Causa: _mark_stale_source_sweeps
corre en cada GET /tasks (el frontend hace poll cada 2s) y marca failed todo
sweep sin terminar con mas de 10 min (3x per_connector_timeout). Un barrido
completo tarda 25-40 min: el marcador lo mata a mitad de camino.

Fix: stale = creado ANTES del boot del proceso (huerfano por restart).
Un sweep vivo del proceso actual nunca es stale, tenga la edad que tenga.
Vale porque api corre single-process (uvicorn sin --workers).
"""

from __future__ import annotations

import datetime as _dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base


@pytest.fixture
def tasks_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _sweep(tasks_db, minutes_ago, status="running", task_type="source_sweep"):
    from app.models import Organization, Task

    org = tasks_db.query(Organization).first()
    if org is None:
        org = Organization(slug="stale-org", name="S", type="university", country="Colombia")
        tasks_db.add(org)
        tasks_db.commit()
    now = _dt.datetime.now().replace(microsecond=0)
    task = Task(
        organization_id=org.id, task_type=task_type, status=status,
        created_at=now - _dt.timedelta(minutes=minutes_ago),
        started_at=now - _dt.timedelta(minutes=minutes_ago),
    )
    tasks_db.add(task)
    tasks_db.commit()
    return task.id


def test_live_sweep_older_than_10min_survives(tasks_db, monkeypatch):
    import app.api.v1.tasks as tasks_mod

    now = _dt.datetime.now().replace(microsecond=0)
    monkeypatch.setattr(tasks_mod, "_PROCESS_BOOTED_AT", now - _dt.timedelta(hours=2))
    tid = _sweep(tasks_db, minutes_ago=30)
    org_id = tasks_db.get(tasks_mod.Task, tid).organization_id
    tasks_mod._mark_stale_source_sweeps(tasks_db, org_id)
    assert tasks_db.get(tasks_mod.Task, tid).status == "running"


def test_orphan_from_previous_boot_is_released(tasks_db, monkeypatch):
    import app.api.v1.tasks as tasks_mod

    now = _dt.datetime.now().replace(microsecond=0)
    monkeypatch.setattr(tasks_mod, "_PROCESS_BOOTED_AT", now - _dt.timedelta(minutes=5))
    tid = _sweep(tasks_db, minutes_ago=30)
    org_id = tasks_db.get(tasks_mod.Task, tid).organization_id
    tasks_mod._mark_stale_source_sweeps(tasks_db, org_id)
    task = tasks_db.get(tasks_mod.Task, tid)
    assert task.status == "failed"
    assert task.finished_at is not None


def test_finished_and_other_types_untouched(tasks_db, monkeypatch):
    import app.api.v1.tasks as tasks_mod

    now = _dt.datetime.now().replace(microsecond=0)
    monkeypatch.setattr(tasks_mod, "_PROCESS_BOOTED_AT", now - _dt.timedelta(minutes=5))
    done = _sweep(tasks_db, minutes_ago=60, status="success")
    other = _sweep(tasks_db, minutes_ago=60, task_type="faculty_match")
    org_id = tasks_db.get(tasks_mod.Task, done).organization_id
    tasks_mod._mark_stale_source_sweeps(tasks_db, org_id)
    assert tasks_db.get(tasks_mod.Task, done).status == "success"
    assert tasks_db.get(tasks_mod.Task, other).status == "running"
