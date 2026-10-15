"""Hard per-source budget for sweeps: hung connectors must fail, not hang.

Context: sdde-bogota (370s), mineducacion (298s) and icetex (259s) exceeded
the 180s per-connector timeout with no enforcement — the sweep only has a
global ~2h window. A hung source must fail at 2x timeout so the tail of the
sweep is bounded.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base


@pytest.fixture
def sweep_db(monkeypatch):
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(per_connector_timeout_seconds=0.05),
    )
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _seed_source(sweep_db):
    from app.models import Organization, Source, SourceRun

    org = Organization(slug="budget-org", name="B", type="university", country="Colombia")
    sweep_db.add(org)
    sweep_db.commit()
    source = Source(
        organization_id=org.id, name="Hog", key="perf-hog",
        base_url="https://example.com/hog",
    )
    sweep_db.add(source)
    sweep_db.commit()
    now = _dt.datetime.now().replace(microsecond=0)
    sweep_db.add(
        SourceRun(
            source_id=source.id, status="running",
            started_at=now - _dt.timedelta(seconds=30),
        )
    )
    sweep_db.commit()
    return org, source


def test_hung_source_fails_at_hard_budget(sweep_db, monkeypatch):
    from app.api.v1.sources import _run_source_via_dispatcher
    from app.models import SourceRun

    org, source = _seed_source(sweep_db)
    org_id, source_id = org.id, source.id
    monkeypatch.setattr("app.api.v1.sources.SessionLocal", lambda: sweep_db)

    async def _slow(db, src, org_id=None):
        await asyncio.sleep(5)
        return None

    monkeypatch.setattr("app.api.v1.sources.dispatcher_run_source", _slow)
    with pytest.raises(TimeoutError, match="hard budget"):
        _run_source_via_dispatcher(source_id, org_id)

    running = sweep_db.query(SourceRun).filter(
        SourceRun.source_id == source_id, SourceRun.status == "running"
    ).all()
    assert running == [], "timed-out source must not leave running rows behind"
    failed = sweep_db.query(SourceRun).filter(
        SourceRun.source_id == source_id, SourceRun.status == "failed"
    ).all()
    assert len(failed) >= 1
    assert failed[0].finished_at is not None


def test_fast_source_unaffected_by_budget(sweep_db, monkeypatch):
    from app.api.v1.sources import _run_source_via_dispatcher

    org, source = _seed_source(sweep_db)
    org_id, source_id = org.id, source.id
    monkeypatch.setattr("app.api.v1.sources.SessionLocal", lambda: sweep_db)

    async def _fast(db, src, org_id=None):
        return "ok"

    monkeypatch.setattr("app.api.v1.sources.dispatcher_run_source", _fast)
    assert _run_source_via_dispatcher(source_id, org_id) == "ok"
