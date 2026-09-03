"""AI v4 + scoring penalty + LLM cache (022 P2)."""
import pytest
from app.core.ai import PROMPT_VERSION, build_local_extraction, _llm_cache_key, clear_llm_cache
from app.schemas.ai import AiOpportunityExtract
def test_prompt_v4(): assert PROMPT_VERSION=="structured-extraction-v4"
def test_local_has_v4_fields():
    d=build_local_extraction("Open call Colombia close 2026-12-01 USD 500,000")
    assert d["prompt_version"]=="structured-extraction-v4" and "funding_amount_raw" in d and "open_date" in d
    assert AiOpportunityExtract.model_validate(d).prompt_version=="structured-extraction-v4"
def test_cache_key(): assert _llm_cache_key("hello")==_llm_cache_key("hello") and _llm_cache_key("a")!=_llm_cache_key("b")
@pytest.mark.asyncio
async def test_cache_hit(monkeypatch):
    from app.core import ai as m; clear_llm_cache(); calls=[]
    async def fake(t): calls.append(t); return {"title":"T","entity":"E","country":"Colombia","category":["research"],"status":"open","close_date":"2026-12-01","requirements":[],"documents_required":[],"summary":"s","risks":[],"recommendation":"r","confidence":0.9,"matched_keywords":[],"risk_level":"low","priority":"high"}
    monkeypatch.setattr(m,"_call_llm",fake); t="Convocatoria cache test "+ "x"*200; r1=await m._extract_one_with_fallback(t); r2=await m._extract_one_with_fallback(t)
    assert len(calls)==1 and r1.data["title"]==r2.data["title"]; clear_llm_cache()
def test_scoring_penalty():
    from app.models import Opportunity, OrganizationProfile; from app.services.scoring import _compute_score; from datetime import datetime
    mk=lambda **kw: Opportunity(title="T",entity="E",country="Colombia",categories=["research"],topics=["research"],summary="s",description="d",requirements=["r"],documents_required=["doc"],**kw)
    prof=OrganizationProfile(organization_id="org1",country="Colombia",areas_of_interest=["research"],organization_type="university",eligible_international=False)
    base=_compute_score(mk(funding_amount_value=None,close_date=None),prof); full=_compute_score(mk(funding_amount_value=500000,close_date=datetime(2027,6,30)),prof)
    assert full["raw"]>base["raw"] and any("Falta fecha" in w for w in base["warnings"])
