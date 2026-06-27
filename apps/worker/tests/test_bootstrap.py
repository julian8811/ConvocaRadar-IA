"""Tests for worker.tasks.bootstrap.seed_default_sources_for_org.

GAP-1 (dashboard-redesign): the task replaces the inline call to
``seed_default_sources`` in POST /auth/register. The contract is:

  1. New org (zero sources) -> task seeds the full default set and
     returns a ``completed`` payload.
  2. Same org re-run -> idempotent: no duplicates, no constraint
     violations, returns ``completed`` again.
  3. Unknown org id -> task returns ``skipped`` instead of raising.

The tests run against a sqlite database that mirrors the same models
the worker would see in production. pytest's pythonpath (set in
pyproject.toml) includes both the worker root and the API root so
``from app.db.seed import seed_default_sources`` resolves to the
shared implementation.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

# Resolve a stable absolute path for the test sqlite file BEFORE setting
# DATABASE_URL — the engine binds to the path at import time, so we
# cannot change it later.
_TEST_DB = Path(__file__).resolve().parent / "test_worker_bootstrap.db"
if _TEST_DB.exists():
    _TEST_DB.unlink()

# Set env before importing any project module so config / DB init see them.
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ.setdefault("INTERNAL_API_KEY", "a" * 64)
os.environ.setdefault("JWT_SECRET", "a" * 64)
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("STORAGE_DIR", "./test_storage_worker_bootstrap")
os.environ.setdefault("SMTP_HOST", "")

from app.db.session import SessionLocal, create_all  # noqa: E402
from app.models import Organization, Source  # noqa: E402
from worker.tasks.bootstrap import seed_default_sources_for_org  # noqa: E402

# Create the schema once at import time. We avoid the per-test
# create_all because SQLAlchemy's engine caches the path; deleting and
# recreating the file behind the engine's back leaves the connection pool
# pointing at a stale inode. Per-test we just truncate the rows.
create_all()


MIN_DEFAULT_SOURCE_COUNT = 25  # seed_default_sources produces >=25 in production


@pytest.fixture(autouse=True)
def _truncate_rows() -> Any:
    """Truncate the test tables between tests so each test starts clean.

    The engine is created at import time and bound to a specific file.
    Deleting/recreating that file would break the connection pool, so we
    keep the file and remove rows instead. seed() is not needed because
    we only exercise seed_default_sources_for_org with fresh orgs.
    """
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
        org = Organization(
            name="Bootstrap Test Org",
            slug=slug,
            type="university",
            country="Colombia",
        )
        db.add(org)
        db.commit()
        db.refresh(org)
        return org
    finally:
        db.close()


def test_seed_default_sources_for_org_idempotent_empty() -> None:
    """A fresh org with zero sources gets the full default set on first run."""
    org = _make_org()
    result = seed_default_sources_for_org(org.id)

    assert result["status"] == "completed", result
    assert result.get("inserted", 0) >= MIN_DEFAULT_SOURCE_COUNT, (
        f"expected >= {MIN_DEFAULT_SOURCE_COUNT} sources inserted on first run, "
        f"got {result.get('inserted')}"
    )

    db = SessionLocal()
    try:
        count = db.query(Source).filter(Source.organization_id == org.id).count()
        assert count >= MIN_DEFAULT_SOURCE_COUNT, f"expected >= {MIN_DEFAULT_SOURCE_COUNT} source rows, got {count}"
    finally:
        db.close()


def test_seed_default_sources_for_org_idempotent_already_seeded() -> None:
    """Re-running on the same org does not duplicate or error.

    seed_default_sources checks for an existing Source by
    (organization_id, key) and updates it in place; the count must stay
    the same and no exception is raised.
    """
    org = _make_org(slug="bootstrap-test-already-seeded")

    first = seed_default_sources_for_org(org.id)
    assert first["status"] == "completed"

    db = SessionLocal()
    try:
        first_count = db.query(Source).filter(Source.organization_id == org.id).count()
        keys_first = sorted(
            s.key for s in db.query(Source).filter(Source.organization_id == org.id).all()
        )
    finally:
        db.close()

    assert first_count >= MIN_DEFAULT_SOURCE_COUNT

    # Second invocation should be a no-op structurally: same keys, no duplicates.
    second = seed_default_sources_for_org(org.id)
    assert second["status"] == "completed"

    db = SessionLocal()
    try:
        second_count = db.query(Source).filter(Source.organization_id == org.id).count()
        keys_second = sorted(
            s.key for s in db.query(Source).filter(Source.organization_id == org.id).all()
        )
    finally:
        db.close()

    assert second_count == first_count, (
        f"second run changed the source count: {first_count} -> {second_count}"
    )
    assert keys_second == keys_first, "second run introduced or removed a source key"
    assert len(keys_second) == len(set(keys_second)), "duplicate source keys after re-run"


def test_seed_default_sources_for_org_missing_org() -> None:
    """An unknown org id returns ``skipped`` instead of raising."""
    result = seed_default_sources_for_org("does-not-exist-1234")
    assert result["status"] == "skipped"
    assert result.get("reason") == "org_not_found"
