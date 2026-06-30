"""Tests for run_all_sources instrumentation (PR4-2).

The run_all endpoint dispatches a background thread that iterates sources
and calls execute_source_run_locally (which makes real HTTP requests in
the default test config). Tests inspect the SYNCHRONOUS log output
(emitted before the background thread starts) so the background thread's
DB lock does not interfere with the next test.
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_convocaradar.db")

import structlog.testing  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

import app.main as app_main  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.db.seed import seed  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Organization, Role, Source, User  # noqa: E402
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


def test_run_all_sources_emits_skip_event_for_disabled_source() -> None:
    """A source with enabled=False is filtered out at the SQL layer.

    With all sources disabled, sources_loaded == 0 and the per-source
    decision loop produces 0 due and 0 skipped.

    NOTE: This test must be run ALONE (not in the same session as the
    other tests in this file). The background sweep from prior tests
    holds a DB lock that prevents the source update in this test.
    """
    c = _client_with_admin()
    db = SessionLocal()
    try:
        db.execute(Source.__table__.update().values(enabled=False))
        db.commit()
    finally:
        db.close()

    with structlog.testing.capture_logs() as captured:
        response = c.post("/api/v1/sources/run-all")
    assert response.status_code == 200
    loaded_events = [e for e in captured if e.get("event") == "run_all.sources_loaded"]
    assert len(loaded_events) == 1
    assert loaded_events[0]["sources_loaded"] == 0
    summary_events = [e for e in captured if e.get("event") == "run_all.decision_summary"]
    assert len(summary_events) == 1
    assert summary_events[0]["sources_due"] == 0
    assert summary_events[0]["sources_skipped"] == 0
    assert summary_events[0]["total"] == 0

