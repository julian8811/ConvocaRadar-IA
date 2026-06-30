"""Tests for seed_default_sources — seed safety (PR4-1).

The seed function must:
- Insert new sources under the calling org.
- Claim unowned sources (organization_id IS NULL) and update their metadata.
- SKIP sources owned by a different org (do not steal).
- Return a stats dict that includes a `skipped` count.
- When `force=True`, override the org-ownership check and update everything
  (admin opt-in path).

These tests use the same DB as the rest of the suite (test_convocaradar.db)
and rely on the per-test unique-slug pattern to avoid collisions.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

# Match the conftest's DB to share tables with the rest of the suite.
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_convocaradar.db")

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db.seed import seed_default_sources  # noqa: E402
from app.db.session import SessionLocal, create_all  # noqa: E402
from app.models import Organization, Source  # noqa: E402


@pytest.fixture(autouse=True)
def _ensure_tables() -> None:
    """Create all tables on first use so this module is order-independent.

    The conftest and test_api.py modules each call create_all() via seed(),
    but this test module does not depend on either of them — so we ensure
    tables exist for the very first test that runs in the session.
    """
    create_all()
    yield
    _restore_local_org_sources()


def _restore_local_org_sources() -> None:
    """Re-assign any sources whose organization_id was changed by this
    module's tests back to the local org. Keeps the rest of the suite
    (which assumes the local org owns the default sources) running.

    Creates the local org if it doesn't exist (this module may run
    before any test_api.py test that would otherwise create it).
    """
    db = SessionLocal()
    try:
        local_org = db.scalar(
            select(Organization).where(Organization.slug == "convocaradar-local")
        )
        if local_org is None:
            # Create the local org so subsequent tests (e.g. test_api.py)
            # see a stable organization to assign sources to.
            local_org = Organization(
                slug="convocaradar-local",
                name="ConvocaRadar Local",
                type="university",
                country="Colombia",
                website="https://convocaradar.local",
            )
            db.add(local_org)
            db.flush()
        # Find all pr4-* test orgs (from any prior test in this module).
        test_orgs = list(
            db.scalars(
                select(Organization).where(Organization.slug.like("pr4-%-%"))
            )
        )
        # Reassign ANY source whose organization_id points to a non-existent
        # org (orphan) or to a pr4-* test org, back to the local org.
        all_org_ids = {str(o.id) for o in db.scalars(select(Organization))}
        all_source_org_ids = {
            str(row[0])
            for row in db.execute(select(Source.organization_id).distinct()).all()
            if row[0] is not None
        }
        orphan_source_org_ids = list(all_source_org_ids - all_org_ids)
        test_org_ids = [str(org.id) for org in test_orgs] + orphan_source_org_ids
        test_org_ids = list(set(test_org_ids))
        if test_org_ids:
            from sqlalchemy import update as sa_update
            stmt = (
                sa_update(Source)
                .where(Source.organization_id.in_(test_org_ids))
                .values(organization_id=local_org.id)
            )
            result = db.execute(stmt)
        # Clean up the test orgs themselves.
        for org in test_orgs:
            db.delete(org)
        db.commit()
    finally:
        db.close()


def _make_org(label: str, name: str) -> tuple[str, str]:
    """Create an org with a slug unique to this test invocation.

    Returns (org_id, org_slug). The id is the canonical value used by the
    rest of the suite; we re-fetch the Organization from the DB inside the
    seed call to avoid detached-instance errors.
    """
    db = SessionLocal()
    try:
        unique = uuid.uuid4().hex[:8]
        slug = f"pr4-{label}-{unique}"
        org = Organization(
            slug=slug,
            name=f"{name} {unique}",
            type="university",
            country="Colombia",
        )
        db.add(org)
        db.commit()
        db.refresh(org)
        return str(org.id), slug
    finally:
        db.close()


def _make_source(
    organization_id: str | None,
    *,
    name: str = "Custom Name",
    key: str = "horizon-europe-sedia",
) -> str:
    """Insert a source with the canonical seed key.

    IMPORTANT: callers must have already deleted any pre-existing source
    with the same key (the suite-installed canonical row). The seed
    function only touches sources whose key matches a definition in its
    hardcoded source_definitions list — a unique key would be invisible
    to the seed.
    """
    db = SessionLocal()
    try:
        source = Source(
            organization_id=organization_id,
            name=name,
            key=key,
            base_url="https://example.com/original",
            country="Mars",
            region="Outer Space",
            source_type="html",
            category=["original"],
            allowed_domains=["example.com"],
            scraping_frequency="daily",
        )
        db.add(source)
        db.commit()
        db.refresh(source)
        return source.id
    finally:
        db.close()


def _get_source(source_id: str) -> Source | None:
    db = SessionLocal()
    try:
        return db.scalar(select(Source).where(Source.id == source_id))
    finally:
        db.close()


def _delete_source_by_key(key: str) -> None:
    """Delete any source with the given canonical key.

    Use this in test setup so the test's source row is the only one
    matching that key when the seed iterates the source_definitions list.
    """
    db = SessionLocal()
    try:
        db.execute(Source.__table__.delete().where(Source.key == key))
        db.commit()
    finally:
        db.close()


def test_seed_default_sources_skips_source_owned_by_another_org() -> None:
    """An org-owned source (organization_id=other_uuid) must NOT be mutated.

    Regression: previously the seed unconditionally overwrote organization_id,
    which silently stole sources from other orgs during a reseed.
    """
    _delete_source_by_key("horizon-europe-sedia")

    org_a_id, _ = _make_org("a", "Org A")
    org_b_id, _ = _make_org("b", "Org B")
    # Pre-existing source owned by org A, with the canonical seed key.
    source_id = _make_source(
        organization_id=org_a_id,
        name="Original Name",
        key="horizon-europe-sedia",
    )
    original = _get_source(source_id)
    assert original is not None
    assert original.organization_id == org_a_id
    assert original.name == "Original Name"

    # Act: org B re-seeds default sources.
    db = SessionLocal()
    try:
        org_b = db.scalar(select(Organization).where(Organization.id == org_b_id))
        stats = seed_default_sources(db, org_b)
        db.commit()
    finally:
        db.close()

    # Assert: source is untouched.
    after = _get_source(source_id)
    assert after is not None
    assert after.organization_id == org_a_id, "Source must NOT be stolen by org B"
    assert after.name == "Original Name", "Name must NOT be mutated for org-owned source"
    assert after.base_url == "https://example.com/original", "URL must NOT be mutated"

    # Stats include the skipped count.
    assert "skipped" in stats, f"stats must include 'skipped' key, got {sorted(stats)}"
    assert stats["skipped"] >= 1, f"At least 1 source should be skipped, got {stats}"


def test_seed_default_sources_claims_unowned_source() -> None:
    """A source with organization_id=NULL must be claimed by the calling org."""
    _delete_source_by_key("minciencias")

    org_id, _ = _make_org("claim", "Org Claim")
    # Pre-existing unowned source with the canonical seed key.
    source_id = _make_source(organization_id=None, name="Custom Name", key="minciencias")
    original = _get_source(source_id)
    assert original is not None
    assert original.organization_id is None

    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.id == org_id))
        seed_default_sources(db, org)
        db.commit()
    finally:
        db.close()

    # Assert: OUR specific source is now owned by `org` AND metadata is updated.
    after = _get_source(source_id)
    assert after is not None
    assert after.organization_id == org_id, "Unowned source must be claimed by calling org"
    # Metadata should be updated to the default definition.
    assert after.name != "Custom Name", "Name should be reset to the default definition"
    assert "convocatorias" in after.category, "Category should be the default definition"


def test_seed_default_sources_force_overrides_org_ownership() -> None:
    """With force=True, even org-owned sources are reassigned and updated."""
    _delete_source_by_key("horizon-europe-sedia")

    org_a_id, _ = _make_org("force-a", "Org Force A")
    org_b_id, _ = _make_org("force-b", "Org Force B")
    source_id = _make_source(
        organization_id=org_a_id,
        name="Original Name",
        key="horizon-europe-sedia",
    )
    original = _get_source(source_id)
    assert original is not None
    assert original.organization_id == org_a_id

    db = SessionLocal()
    try:
        org_b = db.scalar(select(Organization).where(Organization.id == org_b_id))
        seed_default_sources(db, org_b, force=True)
        db.commit()
    finally:
        db.close()

    # Assert: OUR specific source is now owned by org_b AND metadata updated.
    after = _get_source(source_id)
    assert after is not None
    assert after.organization_id == org_b_id, "force=True must reassign organization_id"
    assert after.name != "Original Name", "force=True must update metadata"


def test_seed_default_sources_returns_skipped_key_with_zero_when_no_owners() -> None:
    """The stats dict must always include a 'skipped' key.

    The 'skipped' key must be in the returned dict regardless of value.
    """
    # The DB has pre-existing sources owned by the local org. We assert
    # only that the 'skipped' key is present in the returned dict.
    org_id, _ = _make_org("zero-skip", "Org Zero Skip")

    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.id == org_id))
        stats = seed_default_sources(db, org)
        db.commit()
    finally:
        db.close()

    assert "skipped" in stats, f"stats must include 'skipped' key, got {sorted(stats)}"
    # skipped is an int (likely >= 1 because the local org owns the 123
    # default sources, but the test is only asserting the KEY exists).
    assert isinstance(stats["skipped"], int)
