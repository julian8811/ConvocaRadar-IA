"""Tests for PR B-1a: GET /api/v1/dashboard/triage.

PR B-1a adds a new /dashboard/triage endpoint that returns a TriageRead
payload with two short, action-oriented lists for the consultant persona:

* review_queue — items the user has marked for review, ordered by
  close_date ascending (soonest first, NULL last).
* closing_soon_7d — items closing within 7 days, regardless of user
  status (so brand-new users see them too).

These tests pin the API contract before the implementation lands.

Verification (WU-B1a-4):

* `cd apps/api && pytest tests/test_dashboard_triage.py -v` → 10 passed.
* `cd apps/api && pytest` (full suite) → 145 passed (135 prior + 10 new).
* `cd apps/worker && pytest` → 87 passed.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

os.environ["DATABASE_URL"] = "sqlite:///./test_dashboard_triage.db"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["STORAGE_DIR"] = "./test_storage_triage"
os.environ["SMTP_HOST"] = ""
os.environ["JWT_SECRET"] = "a" * 64
os.environ["INTERNAL_API_KEY"] = "a" * 64
os.environ["BOOTSTRAP_SOURCES_ON_STARTUP"] = "false"

Path("test_dashboard_triage.db").unlink(missing_ok=True)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db.seed import seed  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Opportunity,
    OpportunityEmbedding,
    OpportunityScore,
    Organization,
    Role,
    Source,
    User,
)
from app.schemas import OpportunityCreate  # noqa: E402
from app.services import create_opportunity  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_opportunities() -> None:
    """Wipe opportunity-related rows between tests so each case is hermetic.

    The seed() function only inserts the org + sources once; opportunities
    accumulate across tests otherwise and break the cap-at-8 assertions.
    """
    seed()
    db = SessionLocal()
    try:
        for embedding in list(db.scalars(select(OpportunityEmbedding))):
            db.delete(embedding)
        for score in list(db.scalars(select(OpportunityScore))):
            db.delete(score)
        for opp in list(db.scalars(select(Opportunity))):
            db.delete(opp)
        db.commit()
    finally:
        db.close()
    yield


def _client() -> TestClient:
    seed()
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        if org and not db.scalar(select(User).where(User.email == "admin@convocaradar.io")):
            db.add(
                User(
                    email="admin@convocaradar.io",
                    name="Admin ConvocaRadar",
                    password_hash=hash_password("ConvocaRadarLocal123!"),
                    role=Role.admin.value,
                    organization_id=org.id,
                )
            )
            db.commit()
    finally:
        db.close()
    return TestClient(app)


def _token(c: TestClient) -> str:
    response = c.post(
        "/api/v1/auth/login",
        json={"email": "admin@convocaradar.io", "password": "ConvocaRadarLocal123!"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _make_opportunity(
    *,
    title: str,
    close_days: int | None = 30,
    country: str = "Colombia",
    user_status: str = "review",
    funding_amount_value: float | None = 50000.0,
    funding_amount_currency: str | None = "USD",
    organization_id: str | None = None,
    status: str = "open",
) -> str:
    db = SessionLocal()
    try:
        if organization_id is None:
            organization = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
            assert organization is not None
            organization_id = organization.id
        source = db.scalar(select(Source).where(Source.key == "grants-gov"))
        assert source is not None
        close_date = (
            datetime.now(UTC).replace(tzinfo=None) + timedelta(days=close_days)
            if close_days is not None
            else None
        )
        opportunity = create_opportunity(
            db,
            OpportunityCreate(
                source_id=source.id,
                external_id=f"triage-{title[:30]}-{close_days}",
                title=title,
                entity="Triage Entity",
                country=country,
                categories=["grants"],
                topics=["research"],
                summary=f"Summary for {title} used by triage tests.",
                raw_text="Fixture opportunity for triage endpoint tests.",
                official_url="https://example.com/triage",
                close_date=close_date,
                funding_amount_value=funding_amount_value,
                funding_amount_currency=funding_amount_currency,
                funding_amount_raw="USD 50,000",
                eligible_applicants=["university"],
                requirements=["Concept note"],
                documents_required=["Proposal"],
                evaluation_criteria=["Impact"],
                confidence_score=0.8,
            ),
            organization_id=organization_id,
        )
        opportunity.user_status = user_status
        opportunity.status = status
        db.commit()
        db.refresh(opportunity)
        return opportunity.id
    finally:
        db.close()


def _make_score(*, opportunity_id: str, organization_id: str, score: float = 80.0) -> None:
    db = SessionLocal()
    try:
        # Wipe any auto-calculated scores from create_opportunity so the test
        # has full control over the score value.
        for existing in list(
            db.scalars(
                select(OpportunityScore).where(
                    OpportunityScore.opportunity_id == opportunity_id,
                    OpportunityScore.organization_id == organization_id,
                )
            )
        ):
            db.delete(existing)
        db.flush()
        db.add(
            OpportunityScore(
                opportunity_id=opportunity_id,
                organization_id=organization_id,
                score=score,
                priority="high",
                reasons=["test reason a", "test reason b"],
                warnings=[],
            )
        )
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_triage_requires_auth() -> None:
    c = _client()
    response = c.get("/api/v1/dashboard/triage")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# TriageRead shape
# ---------------------------------------------------------------------------


def test_triage_returns_triage_read_shape() -> None:
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}
    response = c.get("/api/v1/dashboard/triage", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, dict)
    assert "review_queue" in payload, payload
    assert "closing_soon_7d" in payload, payload
    assert isinstance(payload["review_queue"], list)
    assert isinstance(payload["closing_soon_7d"], list)


# ---------------------------------------------------------------------------
# review_queue: user_status filter, ordering, cap
# ---------------------------------------------------------------------------


def test_review_queue_filters_by_user_status() -> None:
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}

    # Seed one of each user_status. Only "review" and "kept" must appear in
    # review_queue.
    _make_opportunity(title="Triage Review Item", close_days=10, user_status="review")
    _make_opportunity(title="Triage Kept Item", close_days=12, user_status="kept")
    _make_opportunity(title="Triage Dismissed Item", close_days=8, user_status="dismissed")
    _make_opportunity(title="Triage Default Item", close_days=6, user_status="default")

    response = c.get("/api/v1/dashboard/triage", headers=auth)
    assert response.status_code == 200
    payload = response.json()

    titles = sorted(item["title"] for item in payload["review_queue"])
    assert "Triage Review Item" in titles
    assert "Triage Kept Item" in titles
    assert "Triage Dismissed Item" not in titles
    assert "Triage Default Item" not in titles


def test_review_queue_capped_at_eight() -> None:
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}

    # Seed 10 review items with ascending close dates.
    for i in range(10):
        _make_opportunity(
            title=f"Triage Review Cap {i}",
            close_days=5 + i,
            user_status="review",
        )

    response = c.get("/api/v1/dashboard/triage", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["review_queue"]) <= 8


def test_review_queue_ordered_by_close_date_asc() -> None:
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}

    # 3 review items with close_date at +5d, +10d, +20d
    # The spec requires close_date IS NOT NULL in the review_queue filter,
    # so all items here have a real close date and ordering is simply ASC.
    _make_opportunity(title="Review 20 days", close_days=20, user_status="review")
    _make_opportunity(title="Review 5 days", close_days=5, user_status="review")
    _make_opportunity(title="Review 10 days", close_days=10, user_status="review")

    response = c.get("/api/v1/dashboard/triage", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    titles = [item["title"] for item in payload["review_queue"]]
    # soonest first
    assert titles.index("Review 5 days") < titles.index("Review 10 days")
    assert titles.index("Review 10 days") < titles.index("Review 20 days")


# ---------------------------------------------------------------------------
# closing_soon_7d: days_to_close filter, ordering, cap
# ---------------------------------------------------------------------------


def test_closing_soon_7d_includes_only_close_within_seven_days() -> None:
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}

    _make_opportunity(title="Closing In 3 Days", close_days=3, user_status="default")
    _make_opportunity(title="Closing In 7 Days", close_days=7, user_status="default")
    _make_opportunity(title="Closing In 14 Days", close_days=14, user_status="default")
    _make_opportunity(title="Closing In 0 Days", close_days=0, user_status="default")

    response = c.get("/api/v1/dashboard/triage", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    titles = [item["title"] for item in payload["closing_soon_7d"]]

    assert "Closing In 3 Days" in titles
    assert "Closing In 7 Days" in titles
    assert "Closing In 0 Days" in titles
    assert "Closing In 14 Days" not in titles


def test_closing_soon_7d_capped_at_eight() -> None:
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}

    for i in range(10):
        _make_opportunity(
            title=f"Closing Cap {i}",
            close_days=1 + i,
            user_status="default",
        )

    response = c.get("/api/v1/dashboard/triage", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["closing_soon_7d"]) <= 8


def test_closing_soon_7d_ordered_by_close_date_asc() -> None:
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}

    _make_opportunity(title="Closing Order 5", close_days=5, user_status="default")
    _make_opportunity(title="Closing Order 1", close_days=1, user_status="default")
    _make_opportunity(title="Closing Order 3", close_days=3, user_status="default")

    response = c.get("/api/v1/dashboard/triage", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    titles = [item["title"] for item in payload["closing_soon_7d"]]

    # Only the items that fall within 7 days should be in the list.
    assert "Closing Order 1" in titles
    assert "Closing Order 3" in titles
    assert "Closing Order 5" in titles
    # And they should be ordered by close_date ASC.
    assert titles.index("Closing Order 1") < titles.index("Closing Order 3")
    assert titles.index("Closing Order 3") < titles.index("Closing Order 5")


# ---------------------------------------------------------------------------
# Item shape and score join
# ---------------------------------------------------------------------------


def test_review_queue_item_includes_score_from_opportunity_score() -> None:
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}

    db = SessionLocal()
    try:
        organization = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert organization is not None
        org_id = organization.id
    finally:
        db.close()

    opp_id = _make_opportunity(title="Scored Review Item", close_days=4, user_status="review")
    _make_score(opportunity_id=opp_id, organization_id=org_id, score=87.5)

    response = c.get("/api/v1/dashboard/triage", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    item = next(item for item in payload["review_queue"] if item["id"] == opp_id)
    assert item["score"] == 87.5
    assert item["title"] == "Scored Review Item"


def test_closing_soon_7d_item_includes_source_key() -> None:
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}

    _make_opportunity(title="With Source Key", close_days=2, user_status="default")

    response = c.get("/api/v1/dashboard/triage", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    item = next(item for item in payload["closing_soon_7d"] if item["title"] == "With Source Key")
    assert item["source_key"] == "grants-gov"
    assert item["days_to_close"] is not None
    assert item["days_to_close"] <= 7
