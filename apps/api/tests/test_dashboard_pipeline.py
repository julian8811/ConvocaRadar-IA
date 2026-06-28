"""Tests for PR B-1b: GET /api/v1/dashboard/pipeline.

PR B-1b adds a new /dashboard/pipeline endpoint that returns a PipelineRead
payload with two lists for the consultant persona:

* top_scored — the highest-scoring opportunities for the current org,
  each item carrying a `score` (float) and a `reasons` list
  (extracted from OpportunityScore.reasons).
* closing_soon — items where ``days_to_close`` falls in [0, 30], ordered
  by close_date ASC (NULL excluded), with ``days_to_close`` as a number.

These tests pin the API contract before the implementation lands. The
tests are hermetic: sqlite-backed TestClient, fixtures seeded inline,
no external services.

Verification (WU-B1b-5):
* ``cd apps/api && pytest tests/test_dashboard_pipeline.py -v`` → all pass.
* ``cd apps/api && pytest`` (full suite) → 145 prior tests + ~10 new
  pipeline tests = ~155 still green.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

os.environ["DATABASE_URL"] = "sqlite:///./test_dashboard_pipeline.db"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["STORAGE_DIR"] = "./test_storage_pipeline"
os.environ["SMTP_HOST"] = ""
os.environ["JWT_SECRET"] = "a" * 64
os.environ["INTERNAL_API_KEY"] = "a" * 64
os.environ["BOOTSTRAP_SOURCES_ON_STARTUP"] = "false"

Path("test_dashboard_pipeline.db").unlink(missing_ok=True)

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
    """Wipe opportunity-related rows between tests so each case is hermetic."""
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
                external_id=f"pipeline-{title[:30]}-{close_days}",
                title=title,
                entity="Pipeline Entity",
                country=country,
                categories=["grants"],
                topics=["research"],
                summary=f"Summary for {title} used by pipeline tests.",
                raw_text="Fixture opportunity for pipeline endpoint tests.",
                official_url="https://example.com/pipeline",
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
        opportunity.status = status
        db.commit()
        db.refresh(opportunity)
        return opportunity.id
    finally:
        db.close()


def _make_score(
    *,
    opportunity_id: str,
    organization_id: str,
    score: float = 80.0,
    reasons: list[str] | None = None,
) -> None:
    db = SessionLocal()
    try:
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
                reasons=reasons if reasons is not None else ["pipeline reason a", "pipeline reason b"],
                warnings=[],
            )
        )
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_pipeline_requires_auth() -> None:
    c = _client()
    response = c.get("/api/v1/dashboard/pipeline")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# PipelineRead shape
# ---------------------------------------------------------------------------


def test_pipeline_returns_pipeline_read_shape() -> None:
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}
    response = c.get("/api/v1/dashboard/pipeline", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, dict)
    assert "top_scored" in payload, payload
    assert "closing_soon" in payload, payload
    assert isinstance(payload["top_scored"], list)
    assert isinstance(payload["closing_soon"], list)


# ---------------------------------------------------------------------------
# top_scored: cap, ordering, score + reasons
# ---------------------------------------------------------------------------


def test_top_scored_capped_at_eight() -> None:
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}

    db = SessionLocal()
    try:
        organization = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert organization is not None
        org_id = organization.id
    finally:
        db.close()

    # 10 scored opportunities with descending scores.
    for i in range(10):
        opp_id = _make_opportunity(title=f"Pipeline Scored {i}", close_days=60)
        _make_score(opportunity_id=opp_id, organization_id=org_id, score=100.0 - i)

    response = c.get("/api/v1/dashboard/pipeline", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["top_scored"]) <= 8


def test_top_scored_items_have_numeric_score_and_reasons() -> None:
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}

    db = SessionLocal()
    try:
        organization = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert organization is not None
        org_id = organization.id
    finally:
        db.close()

    opp_id = _make_opportunity(title="Pipeline With Reasons", close_days=45)
    _make_score(
        opportunity_id=opp_id,
        organization_id=org_id,
        score=92.5,
        reasons=["High amount", "Matches funding type X"],
    )

    response = c.get("/api/v1/dashboard/pipeline", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    item = next(item for item in payload["top_scored"] if item["id"] == opp_id)
    # Numeric score (float, not bucket string).
    assert isinstance(item["score"], (int, float))
    assert item["score"] == 92.5
    # Reasons is a list of strings (may be empty for unscored items).
    assert isinstance(item["reasons"], list)
    assert "High amount" in item["reasons"]
    assert "Matches funding type X" in item["reasons"]


def test_top_scored_ordered_by_score_desc() -> None:
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}

    db = SessionLocal()
    try:
        organization = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert organization is not None
        org_id = organization.id
    finally:
        db.close()

    low_id = _make_opportunity(title="Pipeline Scored Low", close_days=50)
    mid_id = _make_opportunity(title="Pipeline Scored Mid", close_days=50)
    high_id = _make_opportunity(title="Pipeline Scored High", close_days=50)
    _make_score(opportunity_id=low_id, organization_id=org_id, score=40.0)
    _make_score(opportunity_id=mid_id, organization_id=org_id, score=70.0)
    _make_score(opportunity_id=high_id, organization_id=org_id, score=95.0)

    response = c.get("/api/v1/dashboard/pipeline", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    # We only care about the three we scored; build a score→title map.
    by_id = {item["id"]: item for item in payload["top_scored"]}
    assert by_id[high_id]["score"] > by_id[mid_id]["score"] > by_id[low_id]["score"]


# ---------------------------------------------------------------------------
# closing_soon: filter (0-30d, no NULL, no negative), cap, ordering
# ---------------------------------------------------------------------------


def test_closing_soon_excludes_null_and_negative_days_to_close() -> None:
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}

    # Negative: already closed. None: no close date. Both must be excluded.
    _make_opportunity(title="Pipeline Already Closed", close_days=-1)
    _make_opportunity(title="Pipeline No Close Date", close_days=None)

    response = c.get("/api/v1/dashboard/pipeline", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    titles = [item["title"] for item in payload["closing_soon"]]
    assert "Pipeline Already Closed" not in titles
    assert "Pipeline No Close Date" not in titles


def test_closing_soon_includes_only_days_in_zero_to_thirty() -> None:
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}

    _make_opportunity(title="Pipeline Closing In 0 Days", close_days=0)
    _make_opportunity(title="Pipeline Closing In 7 Days", close_days=7)
    _make_opportunity(title="Pipeline Closing In 30 Days", close_days=30)
    _make_opportunity(title="Pipeline Closing In 31 Days", close_days=31)
    _make_opportunity(title="Pipeline Closing In 90 Days", close_days=90)

    response = c.get("/api/v1/dashboard/pipeline", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    titles = [item["title"] for item in payload["closing_soon"]]
    assert "Pipeline Closing In 0 Days" in titles
    assert "Pipeline Closing In 7 Days" in titles
    assert "Pipeline Closing In 30 Days" in titles
    assert "Pipeline Closing In 31 Days" not in titles
    assert "Pipeline Closing In 90 Days" not in titles


def test_closing_soon_capped_at_eight() -> None:
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}

    for i in range(10):
        _make_opportunity(title=f"Pipeline Closing Cap {i}", close_days=1 + i)

    response = c.get("/api/v1/dashboard/pipeline", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["closing_soon"]) <= 8


def test_closing_soon_items_have_numeric_days_to_close() -> None:
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}

    _make_opportunity(title="Pipeline Numeric Days", close_days=5)

    response = c.get("/api/v1/dashboard/pipeline", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    item = next(item for item in payload["closing_soon"] if item["title"] == "Pipeline Numeric Days")
    assert isinstance(item["days_to_close"], int)
    # 0..30 per the contract.
    assert 0 <= item["days_to_close"] <= 30


def test_closing_soon_ordered_by_close_date_asc() -> None:
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}

    _make_opportunity(title="Pipeline Order 10", close_days=10)
    _make_opportunity(title="Pipeline Order 2", close_days=2)
    _make_opportunity(title="Pipeline Order 5", close_days=5)

    response = c.get("/api/v1/dashboard/pipeline", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    titles = [item["title"] for item in payload["closing_soon"]]
    assert titles.index("Pipeline Order 2") < titles.index("Pipeline Order 5")
    assert titles.index("Pipeline Order 5") < titles.index("Pipeline Order 10")
