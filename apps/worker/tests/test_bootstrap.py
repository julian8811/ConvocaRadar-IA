"""GAP-1 (dashboard-redesign): worker.tasks.bootstrap.seed_default_sources_for_org.

The task replaces the inline ``seed_default_sources`` call in
``POST /auth/register`` with an idempotent Celery worker call. The
contract:

  1. New org (zero sources) -> task seeds the full default set.
  2. Same org re-run -> idempotent: no duplicates, no constraint
     violations.
  3. Unknown org id -> task returns ``skipped`` instead of raising.

Tests run against sqlite. The worker's pyproject adds ``../api`` to
``pythonpath`` so the task can import the shared ``app.db.*`` modules
that own the upsert logic.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

# Use an absolute sqlite path so the engine (created at import time) is
# bound to a stable file. Deleting/recreating the file behind the
# engine would break the connection pool.
_TEST_DB = Path(__file__).resolve().parent / "test_worker_bootstrap.db"
if _TEST_DB.exists():
    _TEST_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ.setdefault("INTERNAL_API_KEY", "a" * 64)
os.environ.setdefault("JWT_SECRET", "a" * 64)
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("STORAGE_DIR", "./test_storage_worker_bootstrap")
os.environ.setdefault("SMTP_HOST", "")

from app.db.session import SessionLocal, create_all  # noqa: E402
from app.models import Organization, Source  # noqa: E402
from worker.tasks.bootstrap import seed_default_sources_for_org  # noqa: E402

# Create the schema once at import time. The engine is bound to the
# file path above, so per-test truncation is safer than recreating the
# file (which would leave the connection pool pointing at a stale inode).
create_all()


MIN_DEFAULT_SOURCE_COUNT = 25  # seed_default_sources produces >=25 in production


@pytest.fixture(autouse=True)
def _truncate_rows() -> Any:
    """Truncate the test tables between tests so each test starts clean."""
    db = SessionLocal()
    try:
        db.query(Source).delete()
        db.query(Organization).delete()
        db.commit()
    finally:
        db.close()
    yield


def _make_org(slug: str = "bootstrap-test-org") -> Organization:
    db = SessionLocal()
    try:
        org = Organization(name="Bootstrap Test Org", slug=slug, type="university", country="Colombia")
        db.add(org)
        db.commit()
        db.refresh(org)
        return org
    finally:
        db.close()


def test_seed_default_sources_for_org_idempotent_empty() -> None:
    """A fresh org gets the full default source set on first run."""
    org = _make_org()
    result = seed_default_sources_for_org(org.id)

    assert result["status"] == "completed", result
    assert result.get("inserted", 0) >= MIN_DEFAULT_SOURCE_COUNT

    db = SessionLocal()
    try:
        count = db.query(Source).filter(Source.organization_id == org.id).count()
        assert count >= MIN_DEFAULT_SOURCE_COUNT, f"expected >= {MIN_DEFAULT_SOURCE_COUNT} source rows, got {count}"
    finally:
        db.close()


def test_seed_default_sources_for_org_idempotent_already_seeded() -> None:
    """Re-running on the same org does not duplicate or error.

    ``seed_default_sources`` checks (organization_id, key) and updates in
    place, so the source count and key set are stable across re-runs.
    """
    org = _make_org(slug="bootstrap-test-already-seeded")

    first = seed_default_sources_for_org(org.id)
    assert first["status"] == "completed"

    db = SessionLocal()
    try:
        first_count = db.query(Source).filter(Source.organization_id == org.id).count()
        keys_first = sorted(s.key for s in db.query(Source).filter(Source.organization_id == org.id).all())
    finally:
        db.close()

    assert first_count >= MIN_DEFAULT_SOURCE_COUNT

    second = seed_default_sources_for_org(org.id)
    assert second["status"] == "completed"

    db = SessionLocal()
    try:
        second_count = db.query(Source).filter(Source.organization_id == org.id).count()
        keys_second = sorted(s.key for s in db.query(Source).filter(Source.organization_id == org.id).all())
    finally:
        db.close()

    assert second_count == first_count
    assert keys_second == keys_first
    assert len(keys_second) == len(set(keys_second))


def test_seed_default_sources_for_org_missing_org() -> None:
    """An unknown org id returns ``skipped`` instead of raising."""
    result = seed_default_sources_for_org("does-not-exist-1234")
    assert result["status"] == "skipped"
    assert result.get("reason") == "org_not_found"
