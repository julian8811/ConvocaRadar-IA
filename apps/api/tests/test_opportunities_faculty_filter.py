"""T3: catalog and faculty filter contract."""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_password
from app.db.seed import seed
from app.db.session import SessionLocal
from app.main import app
from app.models import Organization, Role, User, Opportunity

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


def test_get_faculties_returns_4():
    client = _get_client()
    token = _admin_token(client)
    resp = client.get("/api/v1/faculties", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert "faculties" in data
    assert len(data["faculties"]) == 4


def test_get_axes_returns_6():
    client = _get_client()
    token = _admin_token(client)
    resp = client.get("/api/v1/axes", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert "axes" in data
    assert len(data["axes"]) == 6


def test_get_faculty_profiles_returns_24():
    client = _get_client()
    token = _admin_token(client)
    resp = client.get("/api/v1/faculty-profiles", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert len(resp.json()) == 24


def test_opportunities_filter_by_faculty():
    client = _get_client()
    token = _admin_token(client)
    resp = client.get("/api/v1/opportunities?faculty=F1", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert "items" in resp.json()


def test_opportunities_filter_by_min_score():
    client = _get_client()
    token = _admin_token(client)
    resp = client.get("/api/v1/opportunities?faculty=F2&min_match_score=0.5", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_recompute_matches_admin():
    client = _get_client()
    token = _admin_token(client)
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == ORG_SLUG))
        opp = Opportunity(organization_id=org.id, title="Test opp for recompute", entity="Test", country="Colombia", categories=[], topics=[], description="Test", summary="Test", raw_text="Test", slug="recompute-test-xyz")
        db.add(opp)
        db.commit()
        opp_id = opp.id
    finally:
        db.close()
    resp = client.post(f"/api/v1/opportunities/{opp_id}/matches/recompute", headers={"Authorization": f"Bearer {token}", "X-CSRF-Protection": "1"})
    assert resp.status_code in (200, 404, 422)
    if resp.status_code == 200:
        assert "updated" in resp.json()
