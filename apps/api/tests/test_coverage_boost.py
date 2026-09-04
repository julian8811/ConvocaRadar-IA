"""Boost coverage for matching + faculties (W1 fix)."""
import os
import pytest
from sqlalchemy import select
from unittest.mock import AsyncMock, patch
from app.db.session import SessionLocal
from app.models import Opportunity, OpportunityAxisMatch, Organization, FacultyProfile


def _org_id():
    from app.db.seed import seed
    seed()
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        return org.id
    finally:
        db.close()


@pytest.mark.asyncio
async def test_flag_off_returns_empty():
    from app.services.matching import match_opportunity
    from app.core.config import get_settings

    os.environ["FACULTY_MATCH_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        db = SessionLocal()
        try:
            opp = Opportunity(organization_id=_org_id(), title="Test flag off", entity="X", country="Colombia", categories=[], topics=[], description="x", summary="x", raw_text="x", slug="boost-flag-off")
            db.add(opp)
            db.commit()
            res = await match_opportunity(db, opp.id)
            assert res == []
            db.commit()
        finally:
            db.close()
    finally:
        os.environ.pop("FACULTY_MATCH_ENABLED", None)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_verified_by_not_overwritten():
    from app.models import Faculty, InstitutionalAxis
    db = SessionLocal()
    try:
        org_id = _org_id()
        opp = Opportunity(organization_id=org_id, title="Turismo extension verificado", entity="X", country="Colombia", categories=["extension"], topics=["turismo"], description="PBOT turismo", summary="PBOT", raw_text="turismo sostenible PBOT", slug="boost-verified2")
        db.add(opp)
        db.commit()
        oid = opp.id
        # Insert match manually with verified_by
        fac = db.scalar(select(Faculty).where(Faculty.key == "F1"))
        axis = db.scalar(select(InstitutionalAxis).where(InstitutionalAxis.key == "extension"))
        m = OpportunityAxisMatch(organization_id=org_id, opportunity_id=oid, faculty_id=fac.id, axis_id=axis.id, embedding_score=0.6, llm_score=None, final_score=0.6, reasons=["test"], verified_by="tester")
        db.add(m)
        db.commit()
        orig_faculty = fac.id
        from app.services.matching import match_opportunity
        await match_opportunity(db, oid)
        db.commit()
        m2 = db.scalar(select(OpportunityAxisMatch).where(OpportunityAxisMatch.opportunity_id == oid, OpportunityAxisMatch.faculty_id == orig_faculty))
        assert m2 is not None and m2.verified_by == "tester"
    finally:
        db.close()


def test_matrix_and_profile_update():
    from fastapi.testclient import TestClient
    from app.core.security import hash_password
    from app.db.seed import seed
    from app.main import app
    from app.models import Role, User

    seed()
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        if org and not db.scalar(select(User).where(User.email == "admin@convocaradar.io")):
            db.add(User(email="admin@convocaradar.io", name="Admin", password_hash=hash_password("ConvocaRadarLocal123!"), role=Role.admin.value, organization_id=org.id))
            db.commit()
    finally:
        db.close()
    client = TestClient(app)
    resp = client.post("/api/v1/auth/login", json={"email": "admin@convocaradar.io", "password": "ConvocaRadarLocal123!"})
    token = resp.json()["access_token"]
    r = client.get("/api/v1/faculties/matrix", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert "cells" in r.json()
    # Profile update
    db = SessionLocal()
    try:
        prof = db.scalar(select(FacultyProfile))
        pid = prof.id
    finally:
        db.close()
    r2 = client.put(f"/api/v1/faculty-profiles/{pid}", json={"threshold": 0.40}, headers={"Authorization": f"Bearer {token}", "X-CSRF-Protection": "1"})
    assert r2.status_code == 200
    assert r2.json()["threshold"] == 0.40


def test_search_distinct_no_dup():
    from fastapi.testclient import TestClient
    from app.core.security import hash_password
    from app.db.seed import seed
    from app.main import app
    from app.models import Role, User
    seed()
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        if org and not db.scalar(select(User).where(User.email == "admin@convocaradar.io")):
            db.add(User(email="admin@convocaradar.io", name="Admin", password_hash=hash_password("ConvocaRadarLocal123!"), role=Role.admin.value, organization_id=org.id))
            db.commit()
    finally:
        db.close()
    client = TestClient(app)
    resp = client.post("/api/v1/auth/login", json={"email": "admin@convocaradar.io", "password": "ConvocaRadarLocal123!"})
    token = resp.json()["access_token"]
    r = client.get("/api/v1/opportunities?faculty=F1&axis=extension&min_match_score=0.1", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    items = r.json()["items"]
    ids = [x["id"] for x in items]
    assert len(ids) == len(set(ids)), "distinct violation"


def test_health_metrics():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    r = client.get("/api/v1/ops/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert "faculty_match" in r.json()
