"""T4: Bulk DELETE /alerts contract tests."""
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from app.core.security import hash_password
from app.db.seed import seed
from app.db.session import SessionLocal
from app.main import app
from app.models import Alert, Organization, Role, User

ADMIN_EMAIL = "admin@convocaradar.io"
PASSWORD = "ConvocaRadarLocal123!"
ORG_SLUG = "convocaradar-local"


def _admin_token(client: TestClient) -> str:
    resp = client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": PASSWORD})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _get_client():
    seed()
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == ORG_SLUG))
        if org and not db.scalar(select(User).where(User.email == ADMIN_EMAIL)):
            db.add(User(email=ADMIN_EMAIL, name="Admin", password_hash=hash_password(PASSWORD), role=Role.admin.value, organization_id=org.id))
            db.commit()
    finally:
        db.close()
    return TestClient(app)


def _org_id():
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == ORG_SLUG))
        assert org is not None
        return org.id
    finally:
        db.close()


def _clear_alerts():
    db = SessionLocal()
    try:
        for a in list(db.scalars(select(Alert))):
            db.delete(a)
        db.commit()
    finally:
        db.close()


def test_bulk_delete_returns_deleted_count():
    client = _get_client()
    _clear_alerts()
    db = SessionLocal()
    try:
        for i in range(3):
            db.add(Alert(organization_id=_org_id(), alert_type="test", channel="email", recipient="a@a.com", subject=f"S{i}", message="m"))
        db.commit()
    finally:
        db.close()
    token = _admin_token(client)
    resp = client.delete("/api/v1/alerts", headers={"Authorization": f"Bearer {token}", "X-CSRF-Protection": "1"})
    assert resp.status_code == 200
    assert resp.json()["deleted_count"] == 3
    resp2 = client.delete("/api/v1/alerts", headers={"Authorization": f"Bearer {token}", "X-CSRF-Protection": "1"})
    assert resp2.json()["deleted_count"] == 0


def test_bulk_delete_idempotent_empty():
    client = _get_client()
    _clear_alerts()
    token = _admin_token(client)
    resp = client.delete("/api/v1/alerts", headers={"Authorization": f"Bearer {token}", "X-CSRF-Protection": "1"})
    assert resp.status_code == 200
    assert resp.json()["deleted_count"] == 0


def test_bulk_delete_org_isolation():
    client = _get_client()
    _clear_alerts()
    # Create second org
    db = SessionLocal()
    try:
        org_b = Organization(name="Org B", slug="org-b-test", type="other")
        db.add(org_b)
        db.commit()
        db.refresh(org_b)
        org_b_id = org_b.id
        db.add(Alert(organization_id=_org_id(), alert_type="test", channel="email", recipient="a@a.com", subject="A", message="m"))
        db.add(Alert(organization_id=org_b_id, alert_type="test", channel="email", recipient="b@b.com", subject="B", message="m"))
        db.commit()
    finally:
        db.close()
    token = _admin_token(client)
    resp = client.delete("/api/v1/alerts", headers={"Authorization": f"Bearer {token}", "X-CSRF-Protection": "1"})
    assert resp.json()["deleted_count"] == 1
    db = SessionLocal()
    try:
        count_b = db.scalar(select(func.count(Alert.id)).where(Alert.organization_id == org_b_id))
        assert count_b == 1
        # cleanup org_b
        for a in list(db.scalars(select(Alert).where(Alert.organization_id == org_b_id))):
            db.delete(a)
        org_b_obj = db.get(Organization, org_b_id)
        if org_b_obj:
            db.delete(org_b_obj)
        db.commit()
    finally:
        db.close()


def test_bulk_delete_401_without_auth():
    client = _get_client()
    resp = client.delete("/api/v1/alerts")
    assert resp.status_code == 401


def test_bulk_delete_audit_log():
    client = _get_client()
    _clear_alerts()
    # clear old audit logs
    db = SessionLocal()
    try:
        from app.models import AuditLog
        for l in list(db.scalars(select(AuditLog).where(AuditLog.action == "bulk_delete_alerts"))):
            db.delete(l)
        db.commit()
        db.add(Alert(organization_id=_org_id(), alert_type="test", channel="email", recipient="a@a.com", subject="S", message="m"))
        db.commit()
    finally:
        db.close()
    token = _admin_token(client)
    client.delete("/api/v1/alerts", headers={"Authorization": f"Bearer {token}", "X-CSRF-Protection": "1"})
    from app.models import AuditLog
    db = SessionLocal()
    try:
        log = db.scalar(select(AuditLog).where(AuditLog.action == "bulk_delete_alerts").order_by(AuditLog.created_at.desc()))
        assert log is not None
        assert log.metadata_json["deleted_count"] == 1
    finally:
        db.close()


def test_get_alerts_filter_by_faculty():
    client = _get_client()
    token = _admin_token(client)
    resp = client.get("/api/v1/alerts?faculty=F1", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
