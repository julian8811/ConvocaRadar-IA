"""T6 LLM rerank RED tests."""
import pytest
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.core.ai import cosine_similarity
from app.db.session import SessionLocal
from app.models import FacultyProfile, Opportunity, Organization


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
async def test_llm_rerank_strict_enum_validation():
    """LLM must return closed enum faculties/axes, otherwise fallback."""
    from app.services.matching import match_opportunity
    from app.core.config import get_settings

    # Enable LLM
    get_settings.cache_clear()
    orig = get_settings().llm_classification_enabled
    # Force enabled via monkeypatch env
    import os

    os.environ["LLM_CLASSIFICATION_ENABLED"] = "true"
    get_settings.cache_clear()
    try:
        db = _get_db()
        try:
            opp = Opportunity(
                organization_id=_org_id(),
                title="Turismo sostenible PBOT y gestion catastral ambiental",
                entity="MinCiencias",
                country="Colombia",
                categories=["extension"],
                topics=["turismo"],
                description="Convocatoria para PBOT y turismo sostenible",
                summary="PBOT y catastro",
                raw_text="turismo sostenible PBOT",
                slug="test-llm-enum-1",
            )
            db.add(opp)
            db.commit()
            opp_id = opp.id
        finally:
            db.close()
        # Mock LLM to return hallucinated faculty F99
        hallucinated = {"faculty": "F99", "axis": "unknown_axis", "llm_score": 0.9, "reasons": ["hallucinated"]}
        with patch("app.core.ai.classify_faculty_llm", new=AsyncMock(return_value=hallucinated)):
            db = _get_db()
            try:
                matches = await match_opportunity(db, opp_id)
                # Should fallback: no llm_score persisted or llm_score is None
                for m in matches:
                    # If hallucinated, matching should not persist that faculty; llm_score should be None
                    assert m.faculty_id != "F99"
                    # llm_score should be None when validation fails
                db.commit()
            finally:
                db.close()
    finally:
        if not orig:
            os.environ.pop("LLM_CLASSIFICATION_ENABLED", None)
        else:
            os.environ["LLM_CLASSIFICATION_ENABLED"] = "true" if orig else "false"
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_llm_rerank_cache_hit():
    """Cache LRU per hash oportunidad should avoid second LLM call."""
    from app.core.ai import clear_faculty_llm_cache

    clear_faculty_llm_cache()
    from app.core.ai import classify_faculty_llm

    # Mock http to count calls
    call_count = {"n": 0}

    async def fake_call(text):
        call_count["n"] += 1
        return {"faculty": "F1", "axis": "extension", "llm_score": 0.8, "reasons": ["turismo"]}

    with patch("app.core.ai._call_faculty_llm", new=AsyncMock(side_effect=fake_call)):
        await classify_faculty_llm("turismo sostenible PBOT text" * 10)
        await classify_faculty_llm("turismo sostenible PBOT text" * 10)
        # Second call should be cache hit, not increment
        assert call_count["n"] == 1


@pytest.mark.asyncio
async def test_llm_gating_only_if_cosine_ge_threshold():
    """LLM rerank only if cosine >= threshold."""
    from app.services.matching import match_opportunity
    from app.core.config import get_settings
    import os

    os.environ["LLM_CLASSIFICATION_ENABLED"] = "true"
    os.environ["AXIS_MATCH_THRESHOLD"] = "0.95"
    get_settings.cache_clear()
    try:
        db = _get_db()
        try:
            opp = Opportunity(
                organization_id=_org_id(),
                title="Xyzzy unrelated quantum blorpt",
                entity="Unknown",
                country="Colombia",
                categories=["xyz"],
                topics=["xyz"],
                description="Completely unrelated xyzzy",
                summary="xyz",
                raw_text="xyzzy quantum blorpt unrelated",
                slug="test-llm-gating-1",
            )
            db.add(opp)
            db.commit()
            opp_id = opp.id
        finally:
            db.close()
        with patch("app.core.ai.classify_faculty_llm", new=AsyncMock(return_value={"faculty": "F1", "axis": "extension", "llm_score": 0.9, "reasons": ["test"]})) as mock:
            db = _get_db()
            try:
                matches = await match_opportunity(db, opp_id)
                # With very high threshold, no profile passes, so LLM should not be called
                mock.assert_not_called()
                for m in matches:
                    assert m.llm_score is None
            finally:
                db.close()
    finally:
        os.environ.pop("LLM_CLASSIFICATION_ENABLED", None)
        os.environ.pop("AXIS_MATCH_THRESHOLD", None)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_weighting_final_score():
    """final_score = 0.5*emb +0.5*llm, fallback emb only."""
    from app.services.matching import match_opportunity
    import os
    from app.core.config import get_settings

    os.environ["LLM_CLASSIFICATION_ENABLED"] = "true"
    get_settings.cache_clear()
    try:
        db = _get_db()
        try:
            opp = Opportunity(
                organization_id=_org_id(),
                title="Turismo sostenible PBOT y gestion catastral ambiental extension",
                entity="MinCiencias",
                country="Colombia",
                categories=["extension"],
                topics=["turismo"],
                description="PBOT y turismo sostenible extension",
                summary="PBOT",
                raw_text="turismo sostenible PBOT extension",
                slug="test-llm-weight-1",
            )
            db.add(opp)
            db.commit()
            opp_id = opp.id
        finally:
            db.close()
        with patch("app.core.ai.classify_faculty_llm", new=AsyncMock(return_value={"faculty": "F1", "axis": "extension", "llm_score": 0.8, "reasons": ["turismo", "PBOT"]})):
            db = _get_db()
            try:
                matches = await match_opportunity(db, opp_id)
                for m in matches:
                    if m.llm_score is not None:
                        expected = round(0.5 * m.embedding_score + 0.5 * m.llm_score, 4)
                        assert abs(m.final_score - expected) < 0.001
                        assert m.reasons is not None and len(m.reasons) > 0
                db.commit()
            finally:
                db.close()
        # Flag off -> fallback emb only
        os.environ["LLM_CLASSIFICATION_ENABLED"] = "false"
        get_settings.cache_clear()
        with patch("app.core.ai.classify_faculty_llm", new=AsyncMock(return_value={"faculty": "F1", "axis": "extension", "llm_score": 0.8, "reasons": ["turismo"]})):
            db = _get_db()
            try:
                matches2 = await match_opportunity(db, opp_id)
                for m in matches2:
                    assert m.llm_score is None
                    assert m.final_score == m.embedding_score
                db.commit()
            finally:
                db.close()
    finally:
        os.environ.pop("LLM_CLASSIFICATION_ENABLED", None)
        get_settings.cache_clear()
