"""POST /sources/{source_id}/run conflict responses.

RED: the single-run endpoint executes unconditionally — an auto-paused
source inside its 24h cooldown, or a source with a run already in
progress, gets a fresh 200 run instead of an informative 409. The
dispatcher (`app.scraper.dispatcher.run_source`) already encodes both
skip decisions by returning None; the endpoint must surface them as
409 with a motive instead of silently re-running.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta


os.environ.setdefault("DATABASE_URL", "sqlite:///./test_convocaradar.db")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db.seed import seed  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Organization, Role, Source, SourceRun, User  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402


def _client_with_admin() -> TestClient:
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


def _source_id_for(client: TestClient, key: str = "minciencias") -> str:
    sources = client.get("/api/v1/sources")
    assert sources.status_code == 200
    match = [item for item in sources.json() if item["key"] == key]
    assert match, f"seeded source {key!r} not found"
    return match[0]["id"]


def test_run_paused_source_in_cooldown_returns_409():
    """RED: auto-paused source inside 24h cooldown -> 409 paused_cooldown."""
    c = _client_with_admin()
    source_id = _source_id_for(c)
    db = SessionLocal()
    try:
        source = db.get(Source, source_id)
        source.auto_paused = True
        source.last_run_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        db.commit()
        runs_before = db.scalar(
            select(SourceRun).where(SourceRun.source_id == source_id)
        )
        _ = runs_before
        count_before = len(
            list(db.scalars(select(SourceRun).where(SourceRun.source_id == source_id)))
        )
    finally:
        db.close()

    response = c.post(f"/api/v1/sources/{source_id}/run")

    assert response.status_code == 409, f"expected 409, got {response.status_code}: {response.text[:300]}"
    detail = response.json()["detail"]
    assert detail["reason"] == "paused_cooldown"

    db = SessionLocal()
    try:
        count_after = len(
            list(db.scalars(select(SourceRun).where(SourceRun.source_id == source_id)))
        )
        assert count_after == count_before, "409 must not create a SourceRun"
    finally:
        db.close()

    _unpause(source_id)


def _unpause(source_id: str) -> None:
    """Clear auto-pause leftovers so later tests see a clean source."""
    db = SessionLocal()
    try:
        source = db.get(Source, source_id)
        source.auto_paused = False
        db.commit()
    finally:
        db.close()


def test_run_already_running_returns_409():
    """RED: source with a run in progress -> 409 already_running."""
    c = _client_with_admin()
    source_id = _source_id_for(c)
    _unpause(source_id)
    db = SessionLocal()
    try:
        now = datetime.now(UTC).replace(tzinfo=None)
        db.add(
            SourceRun(
                source_id=source_id,
                status="running",
                started_at=now,
                logs=[{"level": "info", "message": "Pre-existing run"}],
            )
        )
        db.commit()
        running_before = len(
            list(
                db.scalars(
                    select(SourceRun).where(
                        SourceRun.source_id == source_id, SourceRun.status == "running"
                    )
                )
            )
        )
    finally:
        db.close()

    response = c.post(f"/api/v1/sources/{source_id}/run")

    assert response.status_code == 409, f"expected 409, got {response.status_code}: {response.text[:300]}"
    detail = response.json()["detail"]
    assert detail["reason"] == "already_running"

    db = SessionLocal()
    try:
        running_after = len(
            list(
                db.scalars(
                    select(SourceRun).where(
                        SourceRun.source_id == source_id, SourceRun.status == "running"
                    )
                )
            )
        )
        assert running_after == running_before, "409 must not start a duplicate run"
    finally:
        db.close()

    _unpause(source_id)
    _clear_runs(source_id)


def _clear_runs(source_id: str) -> None:
    """Delete leftover *running* SourceRuns (shared test DB file).

    Only ``status == "running"`` rows affect the 409 guard; finished runs
    from other modules are left untouched.
    """
    db = SessionLocal()
    try:
        for run in list(
            db.scalars(
                select(SourceRun).where(
                    SourceRun.source_id == source_id, SourceRun.status == "running"
                )
            )
        ):
            db.delete(run)
        db.commit()
    finally:
        db.close()


def test_run_paused_after_cooldown_not_blocked(monkeypatch):
    """Triangulation: cooldown elapsed -> NOT a 409 (pause semantics unchanged).

    The dispatcher would reactivate such a source; the endpoint lets the
    execution through instead of blocking it forever.
    """
    import app.services as app_services

    c = _client_with_admin()
    source_id = _source_id_for(c)
    db = SessionLocal()
    try:
        source = db.get(Source, source_id)
        source.auto_paused = True
        source.last_run_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=25)
        db.commit()
    finally:
        db.close()

    def _sync_fake(db, source, organization_id=None):  # noqa: ANN001, ANN202
        now = datetime.now(UTC).replace(tzinfo=None)
        run = SourceRun(
            source_id=source.id,
            status="success",
            started_at=now,
            finished_at=now,
            items_found=0,
            logs=[],
        )
        db.add(run)
        db.flush()
        return run

    monkeypatch.setattr(app_services, "execute_source_run_locally", _sync_fake)

    # The endpoint imports the symbol inside the handler
    # (``from app.services import execute_source_run_locally``), so the
    # attribute patch above is what the handler resolves.

    response = c.post(f"/api/v1/sources/{source_id}/run")

    assert response.status_code == 200, f"expected pass-through, got {response.status_code}"

    _unpause(source_id)
