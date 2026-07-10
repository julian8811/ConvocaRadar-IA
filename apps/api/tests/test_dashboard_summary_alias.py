"""Tests for PR B-1c: /dashboard/summary deprecated alias.

PR B-1c converts the legacy /dashboard/summary endpoint into a thin
alias that:

1. Returns the same ``DashboardSummaryRead`` shape that the existing
   e2e spec (apps/web/e2e/login-dashboard.spec.ts) and any external
   clients depend on.
2. Emits the deprecation headers on every response (RFC 8594 Sunset
   + RFC 9745 Deprecation + a Link header pointing at the successor
   endpoints /dashboard/triage, /dashboard/pipeline, /dashboard/health).

The implementation in WU-B1c-4 must:
* Continue to satisfy ``test_dashboard_summary`` (in test_api.py).
* Include the "Convocatorias abiertas" / "Alta compatibilidad" string
  matchers the e2e spec relies on, indirectly, by keeping the merged
  shape.
* Emit headers in production shape (not just on the first request).

These tests pin the contract before the refactor lands.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ["DATABASE_URL"] = "sqlite:///./test_dashboard_summary_alias.db"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["STORAGE_DIR"] = "./test_storage_summary_alias"
os.environ["SMTP_HOST"] = ""
os.environ["JWT_SECRET"] = "a" * 64
os.environ["INTERNAL_API_KEY"] = "a" * 64
os.environ["BOOTSTRAP_SOURCES_ON_STARTUP"] = "false"

Path("test_dashboard_summary_alias.db").unlink(missing_ok=True)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db.seed import seed  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Opportunity, Organization, Role, User  # noqa: E402
from app.schemas import OpportunityCreate  # noqa: E402
from app.services import create_opportunity  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_opportunities() -> None:
    seed()
    db = SessionLocal()
    try:
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


async def _seed_opportunity(title: str = "Convocatoria abierta para consultoria") -> None:
    """Seed an opportunity so the summary has a non-empty payload."""
    db = SessionLocal()
    try:
        organization = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert organization is not None
        from app.models import Source

        source = db.scalar(select(Source).where(Source.key == "grants-gov"))
        assert source is not None
        from datetime import UTC, datetime, timedelta

        await create_opportunity(
            db,
            OpportunityCreate(
                source_id=source.id,
                external_id=f"alias-{title[:20]}",
                title=title,
                entity="Alias Entity",
                country="Colombia",
                categories=["grants"],
                topics=["research"],
                summary="Summary used by the alias tests.",
                raw_text="Fixture text for alias tests.",
                official_url="https://example.com/alias",
                close_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=15),
                funding_amount_value=100000.0,
                funding_amount_currency="USD",
                funding_amount_raw="USD 100,000",
                eligible_applicants=["university"],
                requirements=["Concept note"],
                documents_required=["Proposal"],
                evaluation_criteria=["Impact"],
                confidence_score=0.9,
            ),
            organization_id=organization.id,
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_summary_alias_requires_auth() -> None:
    c = _client()
    response = c.get("/api/v1/dashboard/summary")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Shape: must keep the DashboardSummaryRead contract the e2e depends on
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_alias_keeps_legacy_shape() -> None:
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}
    await _seed_opportunity()
    response = c.get("/api/v1/dashboard/summary", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    # Top-level shape must include all the legacy fields the e2e spec
    # (and any external clients) read.
    for key in (
        "total_opportunities",
        "open_opportunities",
        "closing_soon_opportunities",
        "high_match_opportunities",
        "top_scored",
        "closing_soon",
        "status_breakdown",
        "country_breakdown",
        "degraded_sources",
        "failing_sources",
        "source_alerts",
        "data_coverage",
        "profile",
    ):
        assert key in payload, f"missing legacy field: {key}"
    # data_coverage must include the now-nullable embeddings_coverage.
    assert "embeddings_coverage" in payload["data_coverage"]
    # profile must have completeness so the dashboard "Ver resumen
    # numérico" <details> can render.
    assert "completeness" in payload["profile"]


# ---------------------------------------------------------------------------
# Deprecation headers on every response
# ---------------------------------------------------------------------------


def test_summary_alias_emits_deprecation_header() -> None:
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}
    response = c.get("/api/v1/dashboard/summary", headers=auth)
    assert response.status_code == 200
    # RFC 9745: Deprecation: true
    assert response.headers.get("Deprecation") == "true"


def test_summary_alias_emits_sunset_header() -> None:
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}
    response = c.get("/api/v1/dashboard/summary", headers=auth)
    assert response.status_code == 200
    # RFC 8594: Sunset: <HTTP-date>
    sunset = response.headers.get("Sunset")
    assert sunset is not None
    # Must parse as an HTTP-date (RFC 7231 IMF-fixdate: "Sat, 01 Aug 2026 00:00:00 GMT")
    assert "GMT" in sunset.upper()


def test_summary_alias_emits_link_to_successor_endpoints() -> None:
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}
    response = c.get("/api/v1/dashboard/summary", headers=auth)
    assert response.status_code == 200
    link = response.headers.get("Link")
    assert link is not None
    # Must reference all three successor endpoints.
    assert "/api/v1/dashboard/triage" in link
    assert "/api/v1/dashboard/pipeline" in link
    assert "/api/v1/dashboard/health" in link
    # And identify the relation type.
    assert 'rel="successor-version"' in link


def test_summary_alias_headers_present_on_every_call() -> None:
    """Headers must be emitted on every response, not just the first."""
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}
    for _ in range(3):
        response = c.get("/api/v1/dashboard/summary", headers=auth)
        assert response.status_code == 200
        assert response.headers.get("Deprecation") == "true"
        assert response.headers.get("Sunset") is not None
        assert response.headers.get("Link") is not None


# ---------------------------------------------------------------------------
# Backward compatibility: embeddings_coverage is nullable
# ---------------------------------------------------------------------------


def test_summary_alias_embeddings_coverage_is_null_when_no_opportunities() -> None:
    """A brand-new org with no opportunities must see ``null`` (not 0)."""
    c = _client()
    auth = {"Authorization": f"Bearer {_token(c)}"}
    # No _seed_opportunity call — empty org.
    response = c.get("/api/v1/dashboard/summary", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    assert payload["data_coverage"]["embeddings_coverage"] is None
