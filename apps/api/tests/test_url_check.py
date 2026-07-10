"""Tests for GET /opportunities/{id}/url-check.

Strict TDD: tests written FIRST, before the endpoint exists.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.asyncio

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


@pytest.fixture
def clear_db():
    """Clean up the test database between tests."""
    yield
    db = SessionLocal()
    try:
        db.query(Opportunity).delete()
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


async def _make_opportunity(
    *,
    official_url: str | None = "https://example.com/opp",
    application_url: str | None = "https://example.com/apply",
) -> str:
    """Create a single fixture opportunity and return its id.

    Mocks url_is_reachable in _legacy.py so create_opportunity does not hit real HTTP.
    """
    db = SessionLocal()
    try:
        organization = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert organization is not None
        source = db.scalar(select(Source).where(Source.key == "grants-gov"))
        assert source is not None

        with patch("app.services._legacy.url_is_reachable", return_value=True):
            opportunity = await create_opportunity(
                db,
                OpportunityCreate(
                    source_id=source.id,
                    external_id=f"fixture-urlcheck-{datetime.now(UTC).timestamp()}",
                    title="Test Opportunity for URL Check",
                    entity="Test Entity",
                    country="Colombia",
                    categories=["test"],
                    summary="Test opportunity for URL check endpoint.",
                    raw_text="Test raw text for URL check.",
                    official_url=official_url,
                    application_url=application_url,
                    close_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=30),
                ),
                organization_id=organization.id,
            )
        db.commit()
        db.refresh(opportunity)
        return opportunity.id
    finally:
        db.close()


class TestUrlCheckEndpoint:
    """RED: Tests for GET /opportunities/{id}/url-check.

    The endpoint does NOT exist yet — these tests define what it should do.
    """

    async def test_url_check_returns_dict_with_bool_values(self) -> None:
        """url-check should return {"official_url": bool, "application_url": bool}."""
        c = client()
        auth = {"Authorization": f"Bearer {token(c)}"}
        opportunity_id = await _make_opportunity()

        with patch("app.services.url_is_reachable", return_value=True):
            response = c.get(
                f"/api/v1/opportunities/{opportunity_id}/url-check",
                headers=auth,
            )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "official_url" in data
        assert "application_url" in data
        assert isinstance(data["official_url"], bool)
        assert isinstance(data["application_url"], bool)

    async def test_url_check_returns_true_for_reachable_urls(self) -> None:
        """When both URLs are reachable, both should return True."""
        c = client()
        auth = {"Authorization": f"Bearer {token(c)}"}
        opportunity_id = await _make_opportunity()

        with patch("app.services.url_is_reachable", return_value=True):
            response = c.get(
                f"/api/v1/opportunities/{opportunity_id}/url-check",
                headers=auth,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["official_url"] is True
        assert data["application_url"] is True

    async def test_url_check_returns_false_for_unreachable_urls(self) -> None:
        """When both URLs are unreachable, both should return False."""
        c = client()
        auth = {"Authorization": f"Bearer {token(c)}"}
        opportunity_id = await _make_opportunity()

        with patch("app.services.url_is_reachable", return_value=False):
            response = c.get(
                f"/api/v1/opportunities/{opportunity_id}/url-check",
                headers=auth,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["official_url"] is False
        assert data["application_url"] is False

    async def test_url_check_with_none_official_url(self) -> None:
        """When official_url is None, official_url should be False."""
        c = client()
        auth = {"Authorization": f"Bearer {token(c)}"}
        opportunity_id = await _make_opportunity(official_url=None)

        with patch("app.services.url_is_reachable", return_value=True):
            response = c.get(
                f"/api/v1/opportunities/{opportunity_id}/url-check",
                headers=auth,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["official_url"] is False
        assert data["application_url"] is True

    async def test_url_check_with_none_application_url(self) -> None:
        """When application_url is None, application_url should be False."""
        c = client()
        auth = {"Authorization": f"Bearer {token(c)}"}
        opportunity_id = await _make_opportunity(application_url=None)

        with patch("app.services.url_is_reachable", return_value=True):
            response = c.get(
                f"/api/v1/opportunities/{opportunity_id}/url-check",
                headers=auth,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["official_url"] is True
        assert data["application_url"] is False

    async def test_url_check_with_both_none(self) -> None:
        """When both URLs are None, both should be False without calling url_is_reachable."""
        c = client()
        auth = {"Authorization": f"Bearer {token(c)}"}
        opportunity_id = await _make_opportunity(official_url=None, application_url=None)

        with patch("app.services.url_is_reachable", return_value=True) as mock_reachable:
            response = c.get(
                f"/api/v1/opportunities/{opportunity_id}/url-check",
                headers=auth,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["official_url"] is False
        assert data["application_url"] is False
        # url_is_reachable should NOT be called when both URLs are None
        mock_reachable.assert_not_called()

    async def test_url_check_returns_404_for_unknown_opportunity(self) -> None:
        """Unknown opportunity id should return 404."""
        c = client()
        auth = {"Authorization": f"Bearer {token(c)}"}

        response = c.get(
            "/api/v1/opportunities/unknown-id-123/url-check",
            headers=auth,
        )

        assert response.status_code == 404
