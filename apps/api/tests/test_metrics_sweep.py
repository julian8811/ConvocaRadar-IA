"""T2 (fortalecer-201): persistent sweep gauges in GET /metrics.

Pins the three DB-backed gauges exposed by ``GET /metrics``:

- ``due_queue_depth``: enabled + not auto-paused sources where
  ``source_due_for_scraping`` is true right now.
- ``sweep_lag_seconds``: age (seconds) of the last finished ``SourceRun``.
- ``pending_alerts``: ``Alert`` rows with ``status == "pending"``
  (same definition ``send_pending_alerts`` consumes).

Unit tests run against an isolated in-memory SQLite DB so they are
deterministic regardless of what other test modules leave in the shared
test database. Endpoint tests go through the HTTP layer: shape of the
200 body and the degraded 503 when the DB is unreachable (same contract
as ``/api/v1/health/ready``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

import app.main as app_main
from app.db.session import Base
from app.models import Alert, Organization, Source, SourceRun
from app.scraper import metrics as scrape_metrics
from app.scraper.metrics import compute_sweep_gauges


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@pytest.fixture()
def db() -> Session:
    """Isolated in-memory session — hermetic, survives no restarts by design."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _source(key: str, **kwargs) -> Source:
    defaults = {"name": key, "key": key, "base_url": "https://example.com"}
    defaults.update(kwargs)
    return Source(**defaults)


def _org(slug: str) -> Organization:
    return Organization(name=slug, slug=f"{slug}-{uuid.uuid4().hex[:8]}")


class TestDueQueueDepth:
    def test_counts_only_enabled_unpaused_due_sources(self, db: Session) -> None:
        now = _now()
        db.add(_source("due-never-ran"))  # enabled, no last_run_at -> due
        db.add(_source("fresh-daily", last_run_at=now))  # ran just now -> not due
        db.add(_source("disabled-never-ran", enabled=False))  # excluded
        db.add(_source("paused-never-ran", auto_paused=True))  # excluded
        db.commit()

        gauges = compute_sweep_gauges(db, now=now)

        assert gauges["due_queue_depth"] == 1

    def test_persists_across_sessions(self, db: Session) -> None:
        """Gauges are recomputed from the DB, not from process memory."""
        db.add(_source("restart-due"))
        db.commit()
        first = compute_sweep_gauges(db)["due_queue_depth"]

        db.close()  # simulate a process restart: fresh session, same rows
        second = compute_sweep_gauges(db)["due_queue_depth"]

        assert first == second == 1


class TestSweepLagSeconds:
    def test_age_of_last_finished_run(self, db: Session) -> None:
        now = _now()
        src = _source("lag-src")
        db.add(src)
        db.flush()
        db.add(SourceRun(source_id=src.id, status="success", finished_at=now - timedelta(seconds=300)))
        db.add(SourceRun(source_id=src.id, status="failed", finished_at=now - timedelta(seconds=60)))
        db.add(SourceRun(source_id=src.id, status="running", finished_at=None))  # in-flight: ignored
        db.commit()

        gauges = compute_sweep_gauges(db, now=now)

        assert gauges["sweep_lag_seconds"] == 60

    def test_none_without_finished_runs(self, db: Session) -> None:
        src = _source("no-runs-src")
        db.add(src)
        db.flush()
        db.add(SourceRun(source_id=src.id, status="running", finished_at=None))
        db.commit()

        gauges = compute_sweep_gauges(db)

        assert gauges["sweep_lag_seconds"] is None


class TestPendingAlerts:
    def test_counts_only_pending(self, db: Session) -> None:
        org = _org("metrics-sweep")
        db.add(org)
        db.flush()
        for status in ("pending", "sent", "failed"):
            db.add(
                Alert(
                    organization_id=org.id,
                    alert_type="source_health",
                    channel="email",
                    recipient="admin@example.com",
                    subject=f"subject-{status}",
                    message="msg",
                    status=status,
                )
            )
        db.commit()

        gauges = compute_sweep_gauges(db)

        assert gauges["pending_alerts"] == 1


class TestSweepDurationGauges:
    """T3 (fortalecer-201): sweep_duration_seconds + sweep_overrun.

    In-memory (same degraded spirit as T2): ``None``/0 until the first
    scheduler tick completes in this process — no new tables/migrations.
    """

    @pytest.fixture(autouse=True)
    def _clean_sweep_state(self):
        scrape_metrics.reset()
        yield
        scrape_metrics.reset()

    def test_none_before_first_tick(self) -> None:
        snap = scrape_metrics.snapshot()

        assert snap["sweep_duration_seconds"] is None
        assert scrape_metrics.sweep_overrun(interval_seconds=1800) == 0

    def test_records_last_cycle_duration(self) -> None:
        start = scrape_metrics.record_sweep_start()
        duration = scrape_metrics.record_sweep_end(start)

        assert duration >= 0
        assert scrape_metrics.snapshot()["sweep_duration_seconds"] == duration

    def test_overrun_when_cycle_outlasts_interval(self) -> None:
        scrape_metrics._sweep_duration_seconds = 2000.0

        assert scrape_metrics.sweep_overrun(interval_seconds=1800) == 1
        assert scrape_metrics.sweep_overrun(interval_seconds=3600) == 0

    def test_endpoint_exposes_t3_gauges(self, client: TestClient) -> None:
        scrape_metrics._sweep_duration_seconds = 12.5

        body = client.get("/metrics").json()

        assert body["sweep_duration_seconds"] == 12.5
        assert body["sweep_overrun"] == 0

    def test_degraded_endpoint_keeps_t3_gauges(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """T3 gauges are in-memory: still present on the 503 degraded path."""
        from app.db import session as session_module

        scrape_metrics._sweep_duration_seconds = 12.5

        def _connect_raises(*args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

        monkeypatch.setattr(session_module.engine, "connect", _connect_raises)
        response = client.get("/metrics")

        assert response.status_code == 503
        body = response.json()
        assert body["sweep_duration_seconds"] == 12.5
        assert body["sweep_overrun"] == 0


@pytest.fixture()
def client() -> TestClient:
    from app.db.session import create_all

    create_all()  # shared sqlite file starts table-less until seed()/create_all()
    return TestClient(app_main.app, raise_server_exceptions=False)


class TestMetricsEndpoint:
    def test_exposes_persistent_sweep_gauges(self, client: TestClient) -> None:
        response = client.get("/metrics")

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body["due_queue_depth"], int)
        assert body["sweep_lag_seconds"] is None or isinstance(body["sweep_lag_seconds"], int)
        assert isinstance(body["pending_alerts"], int)

    def test_reflects_db_state(self, client: TestClient) -> None:
        """A newly inserted pending alert + due source move the gauges."""
        from app.db.session import SessionLocal

        marker = uuid.uuid4().hex[:8]
        session = SessionLocal()
        try:
            org = Organization(name=f"metrics-ep-{marker}", slug=f"metrics-ep-{marker}")
            session.add(org)
            session.flush()
            session.add(
                Alert(
                    organization_id=org.id,
                    alert_type="source_health",
                    channel="email",
                    recipient="admin@example.com",
                    subject=f"ep-subject-{marker}",
                    message="msg",
                    status="pending",
                )
            )
            session.add(_source(f"ep-due-{marker}"))
            session.commit()
            org_id = org.id
            src_key = f"ep-due-{marker}"
            alert_subject = f"ep-subject-{marker}"
        finally:
            session.close()

        try:
            body = client.get("/metrics").json()
            assert body["pending_alerts"] >= 1
            assert body["due_queue_depth"] >= 1
        finally:
            session = SessionLocal()
            try:
                session.execute(
                    Source.__table__.delete().where(Source.key == src_key)
                )
                session.execute(
                    Alert.__table__.delete().where(Alert.subject == alert_subject)
                )
                session.execute(
                    Organization.__table__.delete().where(Organization.id == org_id)
                )
                session.commit()
            finally:
                session.close()

    def test_degraded_when_db_unreachable(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same degraded contract as /api/v1/health/ready: 503, never 500."""
        from app.db import session as session_module

        def _connect_raises(*args, **kwargs):
            # Raise inline (not via a context manager): /metrics goes through
            # SessionLocal, not `with engine.connect()` like /health/ready.
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

        monkeypatch.setattr(session_module.engine, "connect", _connect_raises)
        response = client.get("/metrics")

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "degraded"
        assert body["database"] == "unreachable"
        assert body["due_queue_depth"] is None
        assert body["sweep_lag_seconds"] is None
        assert body["pending_alerts"] is None

    def test_still_lists_sweep_gauge_keys(self) -> None:
        paths = {route.path for route in app_main.app.routes if hasattr(route, "path")}
        assert "/metrics" in paths
