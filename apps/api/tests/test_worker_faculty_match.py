"""T7 Worker async faculty_match RED tests."""
import asyncio
import time

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Alert, Opportunity, OpportunityAxisMatch, Organization


def _org_id():
    from app.db.seed import seed

    seed()
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert org is not None
        return org.id
    finally:
        db.close()


@pytest.mark.asyncio
async def test_worker_trigger_after_batch_upsert():
    """batch_upsert should trigger faculty_match (async, idempotent)."""
    from app.services.embeddings import EmbeddingBatchService

    svc = EmbeddingBatchService()
    db = SessionLocal()
    try:
        opp = Opportunity(
            organization_id=_org_id(),
            title="Biotecnologia y salud extension investigacion",
            entity="MinCiencias",
            country="Colombia",
            categories=["investigacion"],
            topics=["biotecnologia"],
            description="Biotecnologia salud",
            summary="biotec",
            raw_text="biotecnologia salud investigacion",
            slug="worker-test-trigger-1",
        )
        db.add(opp)
        db.commit()
        opp_id = opp.id
    finally:
        db.close()
    db = SessionLocal()
    try:
        opps = list(db.scalars(select(Opportunity).where(Opportunity.id == opp_id)))
        res = await svc.batch_upsert(db, opps)
        db.commit()
        # After batch_upsert, worker should have been enqueued; check that task exists or matches created via inline
        # For inline mode, matches should be created within <30s SLA
        start = time.time()
        from app.worker import faculty_match_task

        result = await faculty_match_task(db, [opp_id])
        elapsed = time.time() - start
        assert elapsed < 30
        assert result["processed"] >= 1
        db.commit()
    finally:
        db.close()


@pytest.mark.asyncio
async def test_worker_idempotencia():
    from app.worker import faculty_match_task

    db = SessionLocal()
    try:
        opp = Opportunity(
            organization_id=_org_id(),
            title="Turismo sostenible PBOT extension",
            entity="MinCiencias",
            country="Colombia",
            categories=["extension"],
            topics=["turismo"],
            description="PBOT y turismo",
            summary="PBOT",
            raw_text="turismo PBOT",
            slug="worker-test-idem-1",
        )
        db.add(opp)
        db.commit()
        opp_id = opp.id
    finally:
        db.close()
    db = SessionLocal()
    try:
        await faculty_match_task(db, [opp_id])
        db.commit()
        count1 = len(list(db.scalars(select(OpportunityAxisMatch).where(OpportunityAxisMatch.opportunity_id == opp_id))))
        await faculty_match_task(db, [opp_id])
        db.commit()
        count2 = len(list(db.scalars(select(OpportunityAxisMatch).where(OpportunityAxisMatch.opportunity_id == opp_id))))
        assert count1 == count2
    finally:
        db.close()


@pytest.mark.asyncio
async def test_worker_alert_dedup_org_opp_faculty():
    """Alert dedup per (org, opp, faculty)."""
    from app.worker import faculty_match_task

    db = SessionLocal()
    try:
        opp = Opportunity(
            organization_id=_org_id(),
            title="Planeacion y desarrollo social gestion comunitaria",
            entity="MinCiencias",
            country="Colombia",
            categories=["extension"],
            topics=["planeacion"],
            description="Gestion comunitaria y desarrollo territorial",
            summary="planeacion",
            raw_text="planeacion desarrollo social gestion comunitaria",
            slug="worker-test-alert-dedup-1",
        )
        db.add(opp)
        db.commit()
        opp_id = opp.id
    finally:
        db.close()
    db = SessionLocal()
    try:
        await faculty_match_task(db, [opp_id])
        db.commit()
        alerts1 = list(db.scalars(select(Alert).where(Alert.opportunity_id == opp_id)))
        await faculty_match_task(db, [opp_id])
        db.commit()
        alerts2 = list(db.scalars(select(Alert).where(Alert.opportunity_id == opp_id)))
        # dedup: second run should not increase alerts
        assert len(alerts2) == len(alerts1)
        # Check tuple uniqueness
        seen = set()
        for a in alerts2:
            key = (a.organization_id, a.opportunity_id, a.faculty_id)
            assert key not in seen, "duplicate alert tuple"
            seen.add(key)
    finally:
        db.close()
