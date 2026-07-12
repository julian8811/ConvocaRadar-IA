"""Integration tests for the admin probe endpoint.

TDD Cycle: tests written FIRST, then admin endpoint implementation.

Covers:
- 4.5.1: POST /admin/sources/probe-all returns structured JSON
- 4.5.2: Returns 403 for non-admin users
- 4.5.3: Accepts optional source_key query parameter
- 4.5.4: Returns 401 for unauthenticated requests
"""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_convocaradar.db")

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import SessionLocal
from app.db.seed import seed
from app.main import app
from app.models import Organization, Role, Source, User
from app.core.security import hash_password, create_access_token
from app.scraper.probe import ProbeReport, ProbeResult


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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_admin_probe_all_sources_returns_report(monkeypatch) -> None:
    """4.5.1: POST /admin/sources/probe-all returns structured JSON."""
    from app.scraper import probe as probe_module

    now = datetime.now(UTC)
    fake_report = ProbeReport(
        total=2,
        green=1,
        yellow=1,
        red=0,
        results=[
            ProbeResult(source_key="source-a", status="GREEN", candidates_count=5, error_message=None, elapsed_seconds=0.5),
            ProbeResult(source_key="source-b", status="YELLOW", candidates_count=0, error_message=None, elapsed_seconds=0.3),
        ],
        started_at=now,
        finished_at=now,
    )

    async def mock_run_probe(db, source_key=None):
        return fake_report

    monkeypatch.setattr(probe_module, "run_probe", mock_run_probe)

    c = _client_with_admin()
    response = c.post("/api/v1/admin/sources/probe-all")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["green"] == 1
    assert body["yellow"] == 1
    assert body["red"] == 0
    assert len(body["results"]) == 2
    assert body["results"][0]["source_key"] == "source-a"
    assert body["results"][0]["status"] == "GREEN"
    assert body["results"][1]["status"] == "YELLOW"


def test_admin_probe_rejects_non_admin(monkeypatch) -> None:
    """4.5.2: Returns 403 for non-admin users."""
    seed()
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert org is not None
        if not db.scalar(select(User).where(User.email == "user@convocaradar.io")):
            db.add(
                User(
                    email="user@convocaradar.io",
                    name="Regular User",
                    password_hash=hash_password("ConvocaRadarLocal123!"),
                    role=Role.member.value,
                    organization_id=org.id,
                )
            )
            db.commit()
        user = db.scalar(select(User).where(User.email == "user@convocaradar.io"))
        user_id = str(user.id)
    finally:
        db.close()
    token = create_access_token(user_id, extra={"scope": "access", "password_changed_at": 0})
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"

    response = c.post("/api/v1/admin/sources/probe-all")
    assert response.status_code == 403
    assert "Admin role required" in response.text


def test_admin_probe_with_source_key(monkeypatch) -> None:
    """4.5.3: Accepts optional source_key query parameter."""
    from app.scraper import probe as probe_module

    call_log: list[list[str] | None] = []

    async def mock_run_probe(db, source_key=None):
        call_log.append(source_key)
        now = datetime.now(UTC)
        return ProbeReport(
            total=1, green=1, yellow=0, red=0,
            results=[
                ProbeResult(source_key="minciencias", status="GREEN", candidates_count=3, error_message=None, elapsed_seconds=0.2),
            ],
            started_at=now,
            finished_at=now,
        )

    monkeypatch.setattr(probe_module, "run_probe", mock_run_probe)

    c = _client_with_admin()
    response = c.post("/api/v1/admin/sources/probe-all?source_key=minciencias")

    assert response.status_code == 200
    assert call_log == [["minciencias"]]
    body = response.json()
    assert body["total"] == 1
    assert body["results"][0]["source_key"] == "minciencias"


def test_admin_probe_requires_auth() -> None:
    """4.5.4: Returns 401 for unauthenticated requests."""
    c = TestClient(app)
    response = c.post("/api/v1/admin/sources/probe-all")
    assert response.status_code == 401
