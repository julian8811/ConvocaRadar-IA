"""S2 batch p95 — TDD RED→GREEN (flag OFF serial, ON batch 20/32 LRU256, p95)."""
from __future__ import annotations
from unittest.mock import AsyncMock, patch
import pytest
from app.schemas import OpportunityCreate

def _oc(title, raw, lang="es"):
    return OpportunityCreate(source_id="00000000-0000-0000-0000-000000000001", external_id=f"dedup-{title}", title=title, entity="Test Entity", country="Colombia", categories=["innovation"], topics=["test"], description=raw[:120], summary=raw[:120], raw_text=raw, official_url=f"http://example.com/{title.replace(' ', '-')}", language=lang, confidence_score=0.6)

class TestFlagOff:
    @pytest.mark.asyncio
    async def test_runner_flag_off_serial(self):
        from app.scraper import runner
        assert hasattr(runner, "_batch_enrich")
        cands=[_oc(f"T{i}", f"raw {i} $1000 USD") for i in range(3)]
        with patch("app.scraper.runner.get_settings") as ms:
            ms.return_value.extraction_batch_enabled=False
            with patch("app.services.opportunity.create_ai_extraction", new_callable=AsyncMock) as m_s:
                m_s.return_value={"title":"X","entity":"E","country":"Colombia","category":["innovation"],"summary":"s","requirements":[],"documents_required":[],"risks":[],"matched_keywords":[],"confidence":0.6,"funding_amount_raw":"$1000 USD"}
                with patch("app.scraper.runner.extract_opportunities_structured_batch", new_callable=AsyncMock) as m_b:
                    r=await runner._batch_enrich(cands)
                    m_b.assert_not_called(); assert len(r)==3
    @pytest.mark.asyncio
    async def test_opportunity_flag_off_serial(self):
        from app.services import opportunity as opp
        assert hasattr(opp, "enrich_opportunity_payloads_batch")
        datas=[_oc(f"B{i}", f"raw {i}") for i in range(2)]
        with patch("app.services.opportunity.get_settings") as ms:
            ms.return_value.extraction_batch_enabled=False
            with patch("app.services.opportunity.create_ai_extraction", new_callable=AsyncMock) as m_s:
                m_s.return_value={"title":"T","entity":"E","country":"Colombia","category":["innovation"],"summary":"s","requirements":[],"documents_required":[],"risks":[],"matched_keywords":[],"confidence":0.55,"funding_amount_raw":None}
                with patch("app.services.opportunity.extract_opportunities_structured_batch", new_callable=AsyncMock) as m_b:
                    out=await opp.enrich_opportunity_payloads_batch(datas)
                    m_b.assert_not_called(); assert len(out)==2

class TestFlagOn:
    @pytest.mark.asyncio
    async def test_flag_on_chunk20(self):
        from app.scraper import runner
        from app.core.ai import AIExtraction
        cands=[_oc(f"C{i}", f"candidate {i} $5000 COP 2025-12-31") for i in range(25)]
        with patch("app.scraper.runner.get_settings") as ms:
            ms.return_value.extraction_batch_enabled=True
            async def fake(texts, chunk_size=20):
                assert chunk_size==20
                return [AIExtraction(data={"title":f"T{i}","entity":"E","country":"Colombia","category":["innovation"],"summary":texts[i][:20],"requirements":[],"documents_required":[],"risks":[],"matched_keywords":["innovation"],"confidence":0.7,"funding_amount_raw":"$5000 COP"}, confidence=0.7, provider="local") for i in range(len(texts))]
            with patch("app.scraper.runner.extract_opportunities_structured_batch", side_effect=fake) as m_b:
                with patch("app.scraper.runner.build_embeddings_batch", new_callable=AsyncMock) as m_e:
                    m_e.return_value=[[0.1]*64 for _ in range(25)]
                    r=await runner._batch_enrich(cands)
                    assert m_b.call_count==1 and len(r)==25
    @pytest.mark.asyncio
    async def test_embedding_batch_32(self):
        from app.services.embeddings import build_embeddings_batch
        from app.core.ai import clear_llm_cache
        clear_llm_cache()
        texts=[f"unique text {i%10} $1000 USD" for i in range(100)]
        with patch("app.services.embeddings.get_settings") as ms:
            ms.return_value.llm_provider="openai"; ms.return_value.llm_api_key="test-key"; ms.return_value.embedding_model="text-embedding-3-small"; ms.return_value.embedding_dimensions=8; ms.return_value.llm_api_base="https://api.openai.com/v1"; ms.return_value.llm_timeout_seconds=5
            with patch("app.services.embeddings._call_openai_embedding_batch", new_callable=AsyncMock) as m_b:
                async def _ret(ts, dimensions): return [[float(len(x)%5)]*dimensions for x in ts]
                m_b.side_effect=_ret
                res=await build_embeddings_batch(texts)
                assert len(res)==100 and m_b.call_count==4
    @pytest.mark.asyncio
    async def test_lru256(self):
        from app.core.ai import _LLM_CACHE, _LLM_CACHE_ORDER, clear_llm_cache, extract_opportunities_structured_batch
        clear_llm_cache()
        texts=[f"text payload {i} $2000 EUR 2026-01-15" for i in range(300)]
        with patch("app.core.ai.get_settings") as ms:
            ms.return_value.llm_provider="local"; ms.return_value.llm_api_key=None; ms.return_value.embedding_model=""; ms.return_value.extraction_llm_cache_size=256
            res=await extract_opportunities_structured_batch(texts, chunk_size=20)
            assert len(res)==300 and len(_LLM_CACHE)<=256

class TestP95:
    @pytest.mark.asyncio
    async def test_p95_under_4s(self):
        from app.scraper import metrics as m
        from app.scraper.runner import _batch_enrich
        m.reset()
        cands=[_oc(f"P{i}", f"perf {i} $800 COP "*10) for i in range(25)]
        with patch("app.scraper.runner.get_settings") as ms:
            ms.return_value.extraction_batch_enabled=True
            with patch("app.scraper.runner.extract_opportunities_structured_batch", new_callable=AsyncMock) as m_llm:
                async def _chunked(texts, chunk_size=20):
                    from app.core.ai import AIExtraction
                    return [AIExtraction(data={"title":f"T{k}","entity":"E","country":"Colombia","category":["innovation"],"summary":"s","requirements":[],"documents_required":[],"risks":[],"matched_keywords":[],"confidence":0.6}, confidence=0.6, provider="local") for k in range(len(texts))]
                m_llm.side_effect=_chunked
                with patch("app.scraper.runner.build_embeddings_batch", new_callable=AsyncMock) as m_e:
                    m_e.return_value=[[0.0]*64 for _ in range(25)]
                    import time; t0=time.monotonic(); out=await _batch_enrich(cands); dt=time.monotonic()-t0
                    assert len(out)==25 and dt<4.0
                    m.record_scrape(source_key="test-p95", duration_s=dt, items_found=len(out), status="success")
                    snap=m.snapshot()
                    assert snap["scrape_duration_p95"]<=4.0 and "throttled_count" in snap
