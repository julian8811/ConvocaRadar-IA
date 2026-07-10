"""Tests for PR B-1c: GET /api/v1/dashboard/health.

PR B-1c adds a new /dashboard/health endpoint that returns a HealthRead
payload for the consultant persona's "health" lane of the dashboard:

* kpis: a small dict with total/open/closing_soon/high_match counts.
* status_breakdown: list of {name, total} counts by opportunity status.
* country_breakdown: list of {name, total} counts by country (top 8).
* data_coverage: full DashboardDataCoverage (with the new nullable
  embeddings_coverage: float | None).
* sources_health: full per-source health entries (SourceHealthRead shape).
* failing_sources / degraded_sources: integer counts.
* source_alerts: list of DashboardSourceAlert (top 5 degraded+failing).

The endpoint is backend-only: it must be FAST (<500ms target), use the
caller's organization scope, and not break the existing /dashboard/summary
(which becomes a deprecated alias in WU-B1c-4).

These tests pin the API contract before the implementation lands. The
tests are hermetic: sqlite-backed TestClient, fixtures seeded inline,
no external services.

Verification (WU-B1c-5):
* ``cd apps/api && pytest tests/test_dashboard_health.py -v`` → all pass.
* ``cd apps/api && pytest`` (full suite) → still green.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_dashboard_health.db")
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("STORAGE_DIR", "./test_storage_health")
os.environ.setdefault("SMTP_HOST", "")
os.environ.setdefault("JWT_SECRET", "a" * 64)
os.environ.setdefault("INTERNAL_API_KEY", "a" * 64)
os.environ.setdefault("BOOTSTRAP_SOURCES_ON_STARTUP", "false")

Path("test_dashboard_health.db").unlink(missing_ok=True)

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
    # Clear the health cache so stale results from previous tests don't pollute
    from app.api.v1.dashboard import _health_cache
    _health_cache.clear()
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


async def _make_opportunity(
    *,
    title: str,
    close_days: int | None = 30,
    country: str = "Colombia",
    status: str = "open",
    with_embedding: bool = False,
) -> str:
    db = SessionLocal()
    try:
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
        opportunity = await create_opportunity(
            db,
            OpportunityCreate(
                source_id=source.id,
                external_id=f"health-{title[:30]}-{close_days}",
                title=title,
                entity="Health Entity",
                country=country,
                categories=["grants"],
                topics=["research"],
                summary=f"Summary for {title} used by health tests.",
                raw_text="Fixture opportunity for health endpoint tests.",
                official_url="https://example.com/health",
                close_date=close_date,
                funding_amount_value=50000.0,
                funding_amount_currency="USD",
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
        if with_embedding:
            db.add(
                OpportunityEmbedding(
                    opportunity_id=opportunity.id,
                    organization_id=organization_id,
                    embedding=[0.0] * 64,
                    model_version="test-fixture",
                )
            )
        db.commit()
        db.refresh(opportunity)
        return opportunity.id
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_health_requires_auth() -> None:
    c = _client()
    response = c.get("/api/v1/dashboard/health")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# HealthRead shape
# ---------------------------------------------------------------------------


def test_health_returns_health_read_shape() -> None:
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}
    response = c.get("/api/v1/dashboard/health", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, dict)
    # All top-level keys must be present per the HealthRead contract.
    assert "kpis" in payload, payload
    assert "status_breakdown" in payload, payload
    assert "country_breakdown" in payload, payload
    assert "data_coverage" in payload, payload
    assert "sources_health" in payload, payload
    assert "failing_sources" in payload, payload
    assert "degraded_sources" in payload, payload
    assert "source_alerts" in payload, payload


@pytest.mark.asyncio
async def test_health_kpis_have_expected_fields() -> None:
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}
    await _make_opportunity(title="Health KPI A", close_days=10)
    await _make_opportunity(title="Health KPI B", close_days=2, status="closing_soon")
    response = c.get("/api/v1/dashboard/health", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    kpis = payload["kpis"]
    assert isinstance(kpis, dict)
    assert "total" in kpis
    assert "open" in kpis
    assert "closing_soon" in kpis
    assert "high_match" in kpis
    # The kpis must reflect the seeded data.
    assert kpis["total"] >= 2
    assert kpis["open"] >= 1
    assert kpis["closing_soon"] >= 1


@pytest.mark.asyncio
async def test_health_status_and_country_breakdowns_are_lists() -> None:
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}
    await _make_opportunity(title="Health Status A", close_days=10, country="Colombia")
    await _make_opportunity(title="Health Status B", close_days=10, country="Brazil")
    response = c.get("/api/v1/dashboard/health", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["status_breakdown"], list)
    assert isinstance(payload["country_breakdown"], list)
    # Country breakdown must include the seeded countries (top 8).
    countries = {item["name"] for item in payload["country_breakdown"]}
    assert "Colombia" in countries
    assert "Brazil" in countries


# ---------------------------------------------------------------------------
# data_coverage embeddings: nullable semantics
# ---------------------------------------------------------------------------


def test_health_data_coverage_embeddings_is_none_when_no_opportunities() -> None:
    """When the org has zero opportunities, embeddings_coverage MUST be null
    (not 0) — a fresh org should not look 'broken'."""
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}
    response = c.get("/api/v1/dashboard/health", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    coverage = payload["data_coverage"]
    # Nullable: the key must exist and the value must be None, not 0.
    assert "embeddings_coverage" in coverage
    assert coverage["embeddings_coverage"] is None


@pytest.mark.asyncio
async def test_health_data_coverage_embeddings_is_number_when_opportunities_present() -> None:
    """When the org has opportunities, embeddings_coverage MUST be a number
    (0..100). 0.0 is valid (opps exist, none embedded) and is NOT null."""
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}
    await _make_opportunity(title="Health With Opp No Embed", close_days=10, with_embedding=False)
    response = c.get("/api/v1/dashboard/health", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    coverage = payload["data_coverage"]
    # embeddings_coverage is a real number, NOT null.
    assert coverage["embeddings_coverage"] is not None
    assert isinstance(coverage["embeddings_coverage"], (int, float))
    assert 0 <= coverage["embeddings_coverage"] <= 100


@pytest.mark.asyncio
async def test_health_data_coverage_embeddings_partial() -> None:
    """When some opps have embeddings, embeddings_coverage reflects the ratio."""
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}
    # create_opportunity auto-creates an embedding. Wipe all auto-created
    # embeddings first so we have full control: 1 of 2 opps has an embedding.
    await _make_opportunity(title="Health Emb A", close_days=10, with_embedding=False)
    await _make_opportunity(title="Health Emb B", close_days=10, with_embedding=False)
    db = SessionLocal()
    try:
        # Drop every embedding and re-add exactly one (for the first opp).
        for emb in list(db.scalars(select(OpportunityEmbedding))):
            db.delete(emb)
        db.flush()
        opp_a = db.scalar(select(Opportunity).where(Opportunity.title == "Health Emb A"))
        assert opp_a is not None
        db.add(
            OpportunityEmbedding(
                opportunity_id=opp_a.id,
                organization_id=opp_a.organization_id,
                embedding=[0.0] * 64,
                model_version="test-fixture",
            )
        )
        db.commit()
    finally:
        db.close()
    response = c.get("/api/v1/dashboard/health", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    coverage = payload["data_coverage"]
    assert coverage["embeddings_coverage"] is not None
    # Allow some rounding tolerance: 1/2 = 0.5 → 50.0%
    assert 49.0 <= coverage["embeddings_coverage"] <= 51.0


# ---------------------------------------------------------------------------
# source health fields
# ---------------------------------------------------------------------------


def test_health_sources_health_is_list_and_source_alerts_is_list() -> None:
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}
    response = c.get("/api/v1/dashboard/health", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["sources_health"], list)
    assert isinstance(payload["source_alerts"], list)
    assert isinstance(payload["failing_sources"], int)
    assert isinstance(payload["degraded_sources"], int)
