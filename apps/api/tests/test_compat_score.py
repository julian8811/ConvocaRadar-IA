"""R2 compat fixes: score upsert + reachable high threshold.

TDD tests for odd/tasks/panel-reestructurado.md Problem 3 (gap left by R1:
``calculate_score`` blind-inserts, violating ``uq_opportunity_scores_opp_org``).

Coverage not present in ``test_api.py`` (which only asserts the priority
value belongs to the label set):
- second ``calculate_score`` for the same (opportunity, organization) pair
  updates the existing row in place instead of raising ``IntegrityError``.
- ``priority_for_score`` maps 60-74 to high; low/medium bands unchanged.

Verification:
  cd apps/api && python -m pytest tests/test_compat_score.py -q
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import Base
from app.models import Opportunity, OpportunityScore, Organization, OrganizationProfile
from app.services.scoring import calculate_score, priority_for_score


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _org_with_profile(db: Session) -> OrganizationProfile:
    org = Organization(name="R2 Org", slug="r2-org")
    db.add(org)
    db.commit()
    db.refresh(org)
    profile = OrganizationProfile(organization_id=org.id, country="Colombia")
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def _opp(db: Session, title: str) -> Opportunity:
    opp = Opportunity(
        title=title,
        slug=title.lower().replace(" ", "-"),
        entity="Test Entity",
        country="Colombia",
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return opp


# ---------------------------------------------------------------------------
# Upsert: no duplicate row, no IntegrityError
# ---------------------------------------------------------------------------


def test_calculate_score_upserts_instead_of_duplicating(db: Session) -> None:
    profile = _org_with_profile(db)
    opp = _opp(db, "R2 upsert fixture")

    first = calculate_score(db, opp, profile)
    db.commit()
    db.refresh(first)
    first_id = first.id

    second = calculate_score(db, opp, profile)
    db.commit()
    db.refresh(second)

    assert second.id == first_id
    rows = list(
        db.scalars(
            select(OpportunityScore).where(
                OpportunityScore.opportunity_id == opp.id,
                OpportunityScore.organization_id == profile.organization_id,
            )
        )
    )
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# Threshold: high reachable at 60, lower bands unchanged
# ---------------------------------------------------------------------------


def test_high_priority_reachable_below_old_threshold() -> None:
    assert priority_for_score(60) == "high"
    assert priority_for_score(74) == "high"


def test_medium_and_low_bands_unchanged() -> None:
    assert priority_for_score(59) == "medium"
    assert priority_for_score(55) == "medium"
    assert priority_for_score(54) == "low"
    assert priority_for_score(30) == "low"
    assert priority_for_score(29) == "not_recommended"
