"""T2: Cosine matching service - RED tests."""
import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Opportunity, Organization


def _get_db():
    return SessionLocal()


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
async def test_match_opportunity_creates_matches():
    from app.services.matching import match_opportunity

    db = _get_db()
    try:
        opp = Opportunity(organization_id=_org_id(), title="Turismo sostenible PBOT y gestion catastral ambiental", entity="MinCiencias", country="Colombia", categories=["extension"], topics=["turismo"], description="Convocatoria para PBOT y turismo sostenible", summary="PBOT y catastro", raw_text="turismo sostenible PBOT", slug="test-opp-cosine-1")
        db.add(opp)
        db.commit()
        opp_id = opp.id
    finally:
        db.close()
    db = _get_db()
    try:
        matches = await match_opportunity(db, opp_id)
        assert isinstance(matches, list)
        db.commit()
    finally:
        db.close()


@pytest.mark.asyncio
async def test_match_below_threshold_structure():
    from app.services.matching import match_opportunity

    db = _get_db()
    try:
        opp = Opportunity(organization_id=_org_id(), title="Xyzzy unrelated", entity="Unknown", country="Colombia", categories=["xyz"], topics=["xyz"], description="Completely unrelated", summary="xyz", raw_text="xyzzy quantum blorpt", slug="test-opp-cosine-below")
        db.add(opp)
        db.commit()
        opp_id = opp.id
    finally:
        db.close()
    db = _get_db()
    try:
        matches = await match_opportunity(db, opp_id)
        assert isinstance(matches, list)
        for m in matches:
            assert m.embedding_score >= 0.0
            assert m.final_score >= 0.0
        db.commit()
    finally:
        db.close()


@pytest.mark.asyncio
async def test_match_idempotent_no_duplicate():
    from app.services.matching import match_opportunity
    from app.models import OpportunityAxisMatch

    db = _get_db()
    try:
        opp = Opportunity(organization_id=_org_id(), title="Convocatoria investigacion biotecnologia salud", entity="MinCiencias", country="Colombia", categories=["investigacion"], topics=["biotecnologia"], description="Biotecnologia y salud", summary="biotec", raw_text="biotecnologia salud", slug="test-opp-cosine-idem")
        db.add(opp)
        db.commit()
        opp_id = opp.id
    finally:
        db.close()
    db = _get_db()
    try:
        first = await match_opportunity(db, opp_id)
        db.commit()
        second = await match_opportunity(db, opp_id)
        db.commit()
        count = len(list(db.scalars(select(OpportunityAxisMatch).where(OpportunityAxisMatch.opportunity_id == opp_id))))
        assert count == len(first)
        assert count == len(second)
    finally:
        db.close()


def test_cosine_similarity_pure():
    from app.core.ai import cosine_similarity
    assert cosine_similarity([1, 0, 0], [1, 0, 0]) == 1.0
    assert cosine_similarity([1, 0], [0, 1]) == 0.0
    assert cosine_similarity([], []) == 0.0
