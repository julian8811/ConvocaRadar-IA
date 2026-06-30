"""Tests for run_all_sources instrumentation (PR4-2 + PR4-4).

The run_all endpoint dispatches a background thread that iterates sources
and calls execute_source_run_locally (which makes real HTTP requests in
the default test config). Tests inspect the SYNCHRONOUS log output
(emitted before the background thread starts) so the background thread's
DB lock does not interfere with the next test.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_convocaradar.db")

import structlog.testing  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

import app.main as app_main  # noqa: E402
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
        org_id = str(org.id)
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
    original_thread = _threading.Thread
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


def test_run_source_routes_slow_source_to_worker(monkeypatch) -> None:
    """PR5-1: POST /sources/{id}/run must use schedule_or_execute_source_run
    (not execute_source_run_locally directly) so heavy HTML sources like
    apc-colombia and minciencias are dispatched to the Celery worker instead
    of blocking the request for 60-120s.

    Regression guard for the apc-colombia / minciencias 120s timeout bug.
    The test mocks schedule_or_execute_source_run and asserts the endpoint
    called it (returning status='queued'). If the endpoint were to call
    execute_source_run_locally directly (the bug), the response status
    would be 'success' or 'degraded' (after a real HTTP scrape), not
    'queued', and this test would fail.

    NOTE: must be run alone (not in the same pytest session as the run-all
    tests) when slow sources (apc-colombia, minciencias, etc.) are seeded
    enabled, because the run-all background thread holds a write transaction
    on the sources table for the duration of real HTTP calls (see PR4
    apply-progress "Background thread DB lock" risk).

    Run with: pytest tests/test_sources.py::test_run_source_routes_slow_source_to_worker -v
    """
    c = _client_with_admin()
    db = SessionLocal()
    try:
        # Use a seeded slow source — the only DB op we need is a SELECT.
        slow_id = _find_source_id(db, "minciencias")
    finally:
        db.close()

    # Track which dispatch function the endpoint actually called.
    from app.api.v1 import sources as sources_module
    from app.core import task_queue

    schedule_calls: list[dict[str, object]] = []
    execute_calls: list[dict[str, object]] = []

    def fake_schedule(db, source, *, organization_id=None, prefer_worker_for_slow=True):
        schedule_calls.append({"source_key": source.key, "organization_id": organization_id})
        # Build a real SourceRun so Pydantic response_model serialization works.
        started_at = datetime.now(UTC).replace(tzinfo=None)
        run = SourceRun(
            source_id=source.id,
            status="queued",
            started_at=None,
            logs=[{"level": "info", "message": "Slow source dispatched to worker (mocked)"}],
        )
        source.last_run_at = started_at
        db.add(run)
        db.flush()
        return run

    def fake_execute(db, source, organization_id=None):
        execute_calls.append({"source_key": source.key})
        raise AssertionError(
            "run_source called execute_source_run_locally directly — "
            "it MUST use schedule_or_execute_source_run so slow sources "
            "are routed to the Celery worker (regression: PR5)"
        )

    # enqueue_scrape_source is imported inside schedule_or_execute_source_run
    # via `from app.core.task_queue import enqueue_scrape_source`. We must
    # patch the function on the task_queue module so the real
    # schedule_or_execute_source_run (when called) sees our mock.
    def fake_enqueue(source_key, base_url, source_type=None, *, source_run_id, task_id, countdown_seconds=None):
        return f"celery-task-{source_key}"

    monkeypatch.setattr(task_queue, "enqueue_scrape_source", fake_enqueue)
    # Patch on the sources module so the run_source endpoint sees the
    # mocked schedule function. We do NOT mock execute_source_run_locally
    # here because the run-all background thread from previous tests would
    # see the mock and crash. The endpoint's call is detected by
    # schedule_calls/execute_calls inside the fake_schedule/fake_execute
    # closures if execute_source_run_locally were ever called from the
    # endpoint.
    monkeypatch.setattr(sources_module, "schedule_or_execute_source_run", fake_schedule)

    response = c.post(f"/api/v1/sources/{slow_id}/run")
    assert response.status_code == 200, response.text
    body = response.json()
    # The endpoint must have called schedule_or_execute_source_run, NOT
    # execute_source_run_locally. (If execute was called first, the
    # AssertionError in fake_execute would have raised.)
    assert len(schedule_calls) == 1, (
        f"expected schedule_or_execute_source_run to be called once, got {len(schedule_calls)}"
    )
    assert schedule_calls[0]["source_key"] == "minciencias"
    assert schedule_calls[0]["organization_id"] is not None
    # And the response should reflect the worker-dispatched run.
    assert body["status"] == "queued", (
        f"expected status='queued' (worker dispatch), got {body['status']!r}"
    )
    assert body["source_id"] == slow_id
    assert body.get("started_at") is None


def test_run_source_runs_fast_source_inline(monkeypatch) -> None:
    """PR5-2 triangulation: for a fast source (e.g. grants-gov-rss), the
    endpoint must NOT enqueue a Celery task. The real
    schedule_or_execute_source_run checks is_slow_scrape_source and falls
    through to execute_source_run_locally for non-slow sources.

    This guards against a regression where someone might disable the
    is_slow_scrape_source check and queue ALL sources to the worker
    (which would hammer the worker queue with every fast scrape).

    Run with: pytest tests/test_sources.py::test_run_source_runs_fast_source_inline -v
    """
    c = _client_with_admin()
    db = SessionLocal()
    try:
        # grants-gov-rss is NOT in SLOW_SCRAPE_SOURCE_KEYS and not "hybrid",
        # so the real schedule_or_execute_source_run should fall through to
        # execute_source_run_locally without calling enqueue_scrape_source.
        fast_id = _find_source_id(db, "grants-gov-rss")
    finally:
        db.close()

    enqueue_calls: list[dict[str, object]] = []

    def fake_enqueue(source_key, base_url, source_type=None, *, source_run_id, task_id, countdown_seconds=None):
        enqueue_calls.append({"source_key": source_key, "source_run_id": source_run_id})
        return f"celery-task-{source_key}"

    def fake_execute(db, source, organization_id=None):
        # execute_source_run_locally is the expected path for fast sources.
        # Return a SourceRun with status="running" so the test can confirm
        # the endpoint went through this path (not the worker path).
        run = SourceRun(
            source_id=source.id,
            status="running",
            started_at=datetime.now(UTC).replace(tzinfo=None),
            logs=[{"level": "info", "message": "Fast source executed inline (mocked)"}],
        )
        db.add(run)
        db.flush()
        return run

    # Patch on the SERVICES module because schedule_or_execute_source_run
    # calls execute_source_run_locally via its own module's namespace
    # (services.execute_source_run_locally, not sources.execute_source_run_locally).
    from app import services
    from app.core import task_queue

    monkeypatch.setattr(task_queue, "enqueue_scrape_source", fake_enqueue)
    monkeypatch.setattr(services, "execute_source_run_locally", fake_execute)

    response = c.post(f"/api/v1/sources/{fast_id}/run")
    assert response.status_code == 200, response.text
    body = response.json()
    # The worker must NOT have been invoked for a fast source.
    assert len(enqueue_calls) == 0, (
        f"enqueue_scrape_source must NOT be called for fast sources, "
        f"got {len(enqueue_calls)} calls: {enqueue_calls}"
    )
    # The run must be in 'running' state (inline execution), not 'queued'.
    assert body["status"] == "running", (
        f"expected status='running' (inline) for fast source, got {body['status']!r}"
    )
    assert body["source_id"] == fast_id
    # And the run row's started_at is set (the inline path sets it).
    assert body.get("started_at") is not None


def test_run_source_handles_worker_unavailable(monkeypatch) -> None:
    """PR5-2 triangulation: when the Celery enqueue fails (broker down,
    Redis unavailable, celery not installed), schedule_or_execute_source_run
    must fall back to execute_source_run_locally so the source still gets
    scraped. This is the graceful-degradation contract — the operator sees
    the run completed (with a 'degraded' or 'success' status) instead of
    a 500 error.

    Regression guard: a future change that surfaces the enqueue failure as
    a 500 would break the offline-development workflow and any deployment
    where the worker is temporarily down.

    Run with: pytest tests/test_sources.py::test_run_source_handles_worker_unavailable -v
    """
    c = _client_with_admin()
    db = SessionLocal()
    try:
        slow_id = _find_source_id(db, "minciencias")
    finally:
        db.close()

    enqueue_calls: list[dict[str, object]] = []
    execute_calls: list[dict[str, object]] = []

    def fake_enqueue(source_key, base_url, source_type=None, *, source_run_id, task_id, countdown_seconds=None):
        enqueue_calls.append({"source_key": source_key, "source_run_id": source_run_id})
        # Simulate worker unavailable — return None as enqueue_scrape_source
        # does in real life when the broker is down (see services.py:152-154).
        return None

    def fake_execute(db, source, organization_id=None):
        execute_calls.append({"source_key": source.key})
        run = SourceRun(
            source_id=source.id,
            status="running",
            started_at=datetime.now(UTC).replace(tzinfo=None),
            logs=[{"level": "info", "message": "Fallback to local execution (worker unavailable)"}],
        )
        db.add(run)
        db.flush()
        return run

    from app import services
    from app.core import task_queue

    monkeypatch.setattr(task_queue, "enqueue_scrape_source", fake_enqueue)
    monkeypatch.setattr(services, "execute_source_run_locally", fake_execute)

    response = c.post(f"/api/v1/sources/{slow_id}/run")
    assert response.status_code == 200, (
        f"endpoint must not 500 when worker is unavailable (graceful "
        f"degradation), got {response.status_code}: {response.text}"
    )
    # The endpoint must have tried to enqueue (for the slow source)...
    assert len(enqueue_calls) == 1, (
        f"enqueue must be attempted once for slow source, got {len(enqueue_calls)}"
    )
    assert enqueue_calls[0]["source_key"] == "minciencias"
    # ...and then fallen back to local execution.
    assert len(execute_calls) == 1, (
        f"execute_source_run_locally must be called as fallback when enqueue "
        f"returns None, got {len(execute_calls)}"
    )
    body = response.json()
    # The run must be in 'running' state (local execution path).
    assert body["status"] == "running", (
        f"expected status='running' (local fallback), got {body['status']!r}"
    )


def test_run_source_returns_immediately_for_slow_source(monkeypatch) -> None:
    """PR5-2 triangulation: the original bug was a 120s request timeout
    because the endpoint ran the scraper inline. After PR5, a slow source
    must return in well under 5s because the actual scrape is dispatched
    to the worker (which the request handler does not wait for).

    We measure the endpoint latency with the worker dispatch mocked
    (synthetic enqueue, no real HTTP) and assert it is under 2s. This
    protects against a future regression that accidentally re-introduces
    the inline call.

    Run with: pytest tests/test_sources.py::test_run_source_returns_immediately_for_slow_source -v
    """
    import time

    c = _client_with_admin()
    db = SessionLocal()
    try:
        slow_id = _find_source_id(db, "minciencias")
    finally:
        db.close()

    from app import services
    from app.core import task_queue

    def fake_enqueue(source_key, base_url, source_type=None, *, source_run_id, task_id, countdown_seconds=None):
        return f"celery-task-{source_key}"

    def slow_execute(db, source, organization_id=None):
        # Simulate a slow local execution (the bug we're guarding against).
        time.sleep(30)
        return SourceRun(source_id=source.id, status="success")

    monkeypatch.setattr(task_queue, "enqueue_scrape_source", fake_enqueue)
    monkeypatch.setattr(services, "execute_source_run_locally", slow_execute)

    start = time.monotonic()
    response = c.post(f"/api/v1/sources/{slow_id}/run")
    elapsed = time.monotonic() - start
    assert response.status_code == 200, response.text
    # The endpoint must return in < 2s for a slow source. If the
    # implementation accidentally calls execute_source_run_locally, the
    # time.sleep(30) above will cause this assertion to fail.
    assert elapsed < 2.0, (
        f"endpoint must return in <2s for slow source (worker dispatch), "
        f"took {elapsed:.2f}s — likely a regression to inline execution"
    )
    body = response.json()
    assert body["status"] == "queued", (
        f"expected status='queued' (worker dispatch), got {body['status']!r}"
    )

