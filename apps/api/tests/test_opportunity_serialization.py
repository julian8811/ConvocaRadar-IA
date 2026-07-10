"""Regression tests for N+1 HTTP serialization.

Strict TDD: tests written FIRST, before removing the model properties.

T-26: Verify that listing opportunities does NOT trigger url_is_reachable
for every item — that would be an N+1 HTTP request during serialization.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ["DATABASE_URL"] = "sqlite:///./test_convocaradar.db"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["STORAGE_DIR"] = "./test_storage"
os.environ["SMTP_HOST"] = ""
os.environ["JWT_SECRET"] = "a" * 64
os.environ["INTERNAL_API_KEY"] = "a" * 64
os.environ["BOOTSTRAP_SOURCES_ON_STARTUP"] = "false"

Path("test_convocaradar.db").unlink(missing_ok=True)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db.seed import seed  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
import app.main as app_main  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Opportunity, Organization, Role, Source, User  # noqa: E402
from app.schemas import OpportunityCreate  # noqa: E402
from app.services import create_opportunity  # noqa: E402
from app.core.security import hash_password  # noqa: E402


def client() -> TestClient:
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


def token(c: TestClient) -> str:
    response = c.post(
        "/api/v1/auth/login",
        json={"email": "admin@convocaradar.io", "password": "ConvocaRadarLocal123!"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


class TestNoNPlusOneSerialization:
    """RED: Regression test for N+1 HTTP during opportunity listing.

    Before the fix, every Opportunity in a list triggers url_is_reachable
    during Pydantic serialization. This test verifies that listing does NOT
    call url_is_reachable.

    Currently (before removing the model properties) the test FAILS because
    the @property methods on the model call url_is_reachable during
    serialization. After removing them, the test should PASS.
    """

    def _make_opportunities(self, count: int = 5) -> None:
        """Create test opportunities with URLs, bypassing url_is_reachable."""
        db = SessionLocal()
        try:
            org = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
            assert org is not None
            source = db.scalar(select(Source).where(Source.key == "grants-gov"))
            assert source is not None

            with patch("app.services.url_is_reachable", return_value=True):
                for i in range(count):
                    create_opportunity(
                        db,
                        OpportunityCreate(
                            source_id=source.id,
                            external_id=f"fixture-nplus1-{i}-{datetime.now(UTC).timestamp()}",
                            title=f"Test N+1 Opportunity #{i}",
                            entity="Test Entity",
                            country="Colombia",
                            categories=["test"],
                            summary=f"Test opportunity #{i} for N+1 regression.",
                            raw_text=f"Test raw text #{i}.",
                            official_url=f"https://example.com/opp-{i}",
                            application_url=f"https://example.com/apply-{i}",
                            close_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=30 + i),
                        ),
                        organization_id=org.id,
                    )
                db.commit()
        finally:
            db.close()

    def test_listing_opportunities_does_not_call_url_is_reachable(self) -> None:
        """GET /opportunities should NOT trigger url_is_reachable during serialization.

        This is the core N+1 regression test. If the model properties were
        not removed, url_is_reachable will be called for each opportunity,
        causing N+1 HTTP requests.
        """
        c = client()
        auth = {"Authorization": f"Bearer {token(c)}"}
        self._make_opportunities(count=5)

        with patch("app.services.url_is_reachable") as mock_reachable:
            response = c.get("/api/v1/opportunities?page_size=100", headers=auth)

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) >= 5
        # url_is_reachable MUST NOT be called during serialization.
        # If this assertion fails, the N+1 bug is still present:
        # the model @properties are triggering HTTP requests.
        mock_reachable.assert_not_called()

    def test_opportunity_detail_does_not_call_url_is_reachable(self) -> None:
        """GET /opportunities/{id} should NOT trigger url_is_reachable."""
        c = client()
        auth = {"Authorization": f"Bearer {token(c)}"}
        self._make_opportunities(count=1)

        # Grab an opportunity ID from the list
        list_resp = c.get("/api/v1/opportunities?page_size=1", headers=auth)
        assert list_resp.status_code == 200
        opp_id = list_resp.json()["items"][0]["id"]

        with patch("app.services.url_is_reachable") as mock_reachable:
            response = c.get(f"/api/v1/opportunities/{opp_id}", headers=auth)

        assert response.status_code == 200
        mock_reachable.assert_not_called()

    def test_list_100_opportunities_no_nplus1(self) -> None:
        """Listing 100 opportunities should complete without HTTP calls."""
        c = client()
        auth = {"Authorization": f"Bearer {token(c)}"}
        self._make_opportunities(count=100)

        with patch("app.services.url_is_reachable") as mock_reachable:
            response = c.get("/api/v1/opportunities?page_size=100", headers=auth)

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) >= 95
        # The key assertion: zero calls to url_is_reachable during list
        mock_reachable.assert_not_called()
