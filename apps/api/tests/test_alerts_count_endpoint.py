"""Regression guard for GET /api/v1/alerts/count.

The endpoint body builds ``select(func.count(Alert.id))`` but did not import
``sqlalchemy.func`` — every request resolved the name at call time, raised
``NameError`` and surfaced as HTTP 500, breaking the in-app pending-alerts
badge. These tests pin the real query execution through the HTTP layer.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_password  # noqa: E402
from app.db.seed import seed  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Alert, Organization, Role, User  # noqa: E402

ADMIN_EMAIL = "admin@convocaradar.io"
PASSWORD = "ConvocaRadarLocal123!"
ORG_SLUG = "convocaradar-local"


def _admin_token(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": PASSWORD},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.fixture()
def client() -> TestClient:
    seed()
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == ORG_SLUG))
        if org is not None and not db.scalar(select(User).where(User.email == ADMIN_EMAIL)):
            db.add(
                User(
                    email=ADMIN_EMAIL,
                    name="Admin ConvocaRadar",
                    password_hash=hash_password(PASSWORD),
                    role=Role.admin.value,
                    organization_id=org.id,
                )
            )
            db.commit()
    finally:
        db.close()
    return TestClient(app)


class TestAlertsCountEndpoint:
    def _org_id(self) -> str:
        db = SessionLocal()
        try:
            org = db.scalar(select(Organization).where(Organization.slug == ORG_SLUG))
            assert org is not None
            return org.id
        finally:
            db.close()

    def _clear_pending_alerts(self) -> None:
        db = SessionLocal()
        try:
            for alert in list(db.scalars(select(Alert).where(Alert.status == "pending"))):
                db.delete(alert)
            db.commit()
        finally:
            db.close()

    def test_pending_alert_is_counted(self, client: TestClient) -> None:
        self._clear_pending_alerts()
        db = SessionLocal()
        try:
            db.add(
                Alert(
                    organization_id=self._org_id(),
                    alert_type="test",
                    channel="email",
                    recipient="ops@example.com",
                    subject="Pending badge",
                    message="count me",
                    status="pending",
                )
            )
            db.commit()
        finally:
            db.close()

        token = _admin_token(client)
        response = client.get("/api/v1/alerts/count", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json() == {"pending": 1}

    def test_no_pending_alerts_returns_zero(self, client: TestClient) -> None:
        self._clear_pending_alerts()
        token = _admin_token(client)
        response = client.get("/api/v1/alerts/count", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json() == {"pending": 0}
