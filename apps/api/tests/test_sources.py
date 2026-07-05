"""Tests for run_all_sources instrumentation (PR4-2 + PR4-4).

The run_all endpoint dispatches a background thread that iterates sources
and calls execute_source_run_locally (which makes real HTTP requests in
the default test config). Tests inspect the SYNCHRONOUS log output
(emitted before the background thread starts) so the background thread's
DB lock does not interfere with the next test.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_convocaradar.db")

import structlog.testing  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.db.seed import seed  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Organization, Role, Source, SourceRun, User  # noqa: E402
from app.core.security import hash_password, create_access_token  # noqa: E402


def _client_with_admin() -> TestClient:
    """Build a test client with the local org seeded and an admin user."""
    seed()
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert org is not None
        if not db.scalar(select(User).where(User.email == "admin@convocaradar.io")):
            db.add(
                User(
                    email="admin@convocaradar.io",
                    name="Admin",
                    password_hash=hash_password("ConvocaRadarLocal123!"),
                    role=Role.admin.value,
                    organization_id=org.id,
                )
            )
            db.commit()
        admin = db.scalar(select(User).where(User.email == "admin@convocaradar.io"))
        admin_id = str(admin.id)
    finally:
        db.close()
    token = create_access_token(admin_id, extra={"scope": "access", "password_changed_at": 0})
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def test_run_all_sources_emits_sources_loaded_event() -> None:
    """POST /sources/run-all must log how many sources it loaded.

    The sources_loaded log line is emitted SYNCHRONOUSLY before the
    background thread starts, so it is captured by structlog.testing.capture_logs.
    """
    c = _client_with_admin()
    with structlog.testing.capture_logs() as captured:
        response = c.post("/api/v1/sources/run-all")
    assert response.status_code == 200
    loaded_events = [
        e for e in captured
        if e.get("event") == "run_all.sources_loaded"
    ]
    assert len(loaded_events) >= 1, f"expected run_all.sources_loaded event, got events: {[e.get('event') for e in captured]}"
    loaded = loaded_events[0]
    assert loaded["sources_loaded"] >= 1
    assert loaded["org_id"]


def test_run_all_sources_emits_decision_summary_event() -> None:
    """The endpoint must emit a summary event with processed/skipped counts.

    The decision_summary log line is the single most useful log line for
    diagnosing the run-all empty-return bug: if sources_due == 0, the bug
    is upstream of the dispatch (e.g. a frequency mismatch or org-scope filter).
    """
    c = _client_with_admin()
    with structlog.testing.capture_logs() as captured:
        response = c.post("/api/v1/sources/run-all")
    assert response.status_code == 200

    summary_events = [
        e for e in captured
        if e.get("event") == "run_all.decision_summary"
    ]
    assert len(summary_events) >= 1, (
        f"expected run_all.decision_summary event, got events: {[e.get('event') for e in captured]}"
    )
    summary = summary_events[0]
    assert "sources_due" in summary
    assert "sources_skipped" in summary
    assert "total" in summary
    # The three counts must be internally consistent.
    assert summary["sources_due"] + summary["sources_skipped"] == summary["total"]


def test_run_all_sources_endpoint_response_unchanged_by_instrumentation() -> None:
    """The endpoint's return value must NOT change — only logs are added.

    The instrumentation must be observability-only: it must not affect the
    endpoint's return value or the sweep's behavior.
    """
    c = _client_with_admin()
    with structlog.testing.capture_logs():
        response = c.post("/api/v1/sources/run-all")
    assert response.status_code == 200
    payload = response.json()
    assert "status" in payload
    assert "sources" in payload
    assert payload["status"] == "started"
    assert isinstance(payload["sources"], int)
    assert payload["sources"] >= 1


def test_run_all_sources_logs_failure_when_execute_raises(monkeypatch) -> None:
    """PR4-4: when execute_source_run_locally raises, the background sweep
    must log a structured error event with full context (source key, error
    type, error message).

    Previously the except silently swallowed the error, leaving the
    operator with no way to know why runs were not being created.
    """
    # Make all sources unowned so the endpoint picks them up.
    c = _client_with_admin()

    # Make execute_source_run_locally raise a deterministic error.
    from app.api.v1 import sources as sources_module

    def fake_execute(db, source, organization_id=None):
        raise RuntimeError("simulated scraper failure for test")

    # Disable the slow-scrape path so all sources go through execute.
    monkeypatch.setattr(sources_module, "execute_source_run_locally", fake_execute)
    # Make threading.Thread synchronous so we can capture the background
    # thread's log output. Use a target wrapper that runs the function
    # directly instead of in a thread.
    import threading as _threading
    def sync_thread(target, *args, **kwargs):
        class SyncThread:
            def __init__(self):
                self._target = target
            def start(self):
                self._target()
        return SyncThread()
    monkeypatch.setattr(_threading, "Thread", sync_thread)

    with structlog.testing.capture_logs() as captured:
        response = c.post("/api/v1/sources/run-all")
    assert response.status_code == 200
    # The structured failure event MUST be emitted.
    failure_events = [e for e in captured if e.get("event") == "run_all.source_failed"]
    assert len(failure_events) >= 1, (
        f"expected run_all.source_failed event when scraper fails, "
        f"got events: {[e.get('event') for e in captured]}"
    )
    failure = failure_events[0]
    assert "source_key" in failure
    assert failure["error_type"] == "RuntimeError"
    assert "simulated scraper failure" in failure["error_message"]
    # The completed event must report failed > 0.
    completed_events = [e for e in captured if e.get("event") == "run_all.completed"]
    assert len(completed_events) >= 1
    assert completed_events[0]["failed"] >= 1
    assert completed_events[0]["processed"] == 0


def _find_source_id(db, key: str) -> str:
    src = db.scalar(select(Source).where(Source.key == key))
    assert src is not None, f"seeded source {key!r} not found"
    return str(src.id)


def test_run_source_runs_inline(monkeypatch) -> None:
    """After Celery/Redis removal, all sources run inline. The endpoint
    calls execute_source_run_locally directly and returns a 'running'
    SourceRun.

    Run with: pytest tests/test_sources.py::test_run_source_runs_inline -v
    """
    c = _client_with_admin()
    db = SessionLocal()
    try:
        src_id = _find_source_id(db, "minciencias")
    finally:
        db.close()

    execute_calls: list[dict[str, object]] = []

    def fake_execute(db, source, organization_id=None):
        execute_calls.append({"source_key": source.key})
        run = SourceRun(
            source_id=source.id,
            status="running",
            started_at=datetime.now(UTC).replace(tzinfo=None),
            logs=[{"level": "info", "message": "Mocked inline execution"}],
        )
        db.add(run)
        db.flush()
        return run

    from app import services

    monkeypatch.setattr(services, "execute_source_run_locally", fake_execute)

    response = c.post(f"/api/v1/sources/{src_id}/run")
    assert response.status_code == 200, response.text
    assert len(execute_calls) == 1, (
        f"expected execute_source_run_locally to be called once, got {len(execute_calls)}"
    )
    assert execute_calls[0]["source_key"] == "minciencias"
    body = response.json()
    assert body["status"] == "running", (
        f"expected status='running' (inline), got {body['status']!r}"
    )
    assert body["source_id"] == src_id


def test_run_source_returns_within_timeout(monkeypatch) -> None:
    """All sources run inline now, but the endpoint must still return
    within a reasonable time. Use a fast mock to verify the endpoint
    itself is not the bottleneck.

    Run with: pytest tests/test_sources.py::test_run_source_returns_within_timeout -v
    """
    import time

    c = _client_with_admin()
    db = SessionLocal()
    try:
        src_id = _find_source_id(db, "minciencias")
    finally:
        db.close()

    def instant_execute(db, source, organization_id=None):
        run = SourceRun(
            source_id=source.id,
            status="running",
            started_at=datetime.now(UTC).replace(tzinfo=None),
            logs=[],
        )
        db.add(run)
        db.flush()
        return run

    from app import services

    monkeypatch.setattr(services, "execute_source_run_locally", instant_execute)

    start = time.monotonic()
    response = c.post(f"/api/v1/sources/{src_id}/run")
    elapsed = time.monotonic() - start
    assert response.status_code == 200, response.text
    assert elapsed < 5.0, f"endpoint must return in <5s, took {elapsed:.2f}s"

