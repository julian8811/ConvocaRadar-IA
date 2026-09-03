"""Slice 1 — RED tests for gate 0.82 OR funding missing, funding mirror, semaphore 25.

Strict TDD: these tests are written first and MUST fail against the
pre-fix implementation (gate <0.7 only, no funding mirror, unbounded gather).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.connectors.base import OpportunityCandidate
from app.connectors.configurable_html import ConfigurableHtmlConnector

VALID_CONFIG = {
    "list_selectors": [".card"],
    "title_selectors": ["h2 a"],
    "link_selectors": ["a[href]"],
    "content_selectors": [".content"],
    "date_labels": ["Cierre:"],
    "detail_enrichment": True,
}

DETAIL_WITH_FUNDING = """<html><body>
<h1>Detail Title</h1>
<p>Funding amount: $50,000,000 COP</p>
</body></html>"""

GENERIC_DETAIL = """<html><body><h1>T</h1></body></html>"""


def _cand(url: str, conf: float, funding: str | None) -> OpportunityCandidate:
    return OpportunityCandidate(
        title="T",
        entity="E",
        country="Colombia",
        official_url=url,
        summary="s",
        raw_text="raw",
        confidence_score=conf,
        funding_amount_raw=funding,
    )


class TestGateCorrection:
    """Requirement: gate MUST be conf<0.82 OR funding IS NULL."""

    @pytest.mark.asyncio
    async def test_gate_075_missing_triggers_fetch(self):
        c = _cand("http://example.com/a", 0.75, None)
        connector = ConfigurableHtmlConnector("k", "http://example.com", VALID_CONFIG)
        with patch("app.connectors.common.fetch_httpx_text", new=AsyncMock(return_value=("http://example.com/a", GENERIC_DETAIL, "text/html"))) as mock:
            await connector._deep_fetch_candidates([c])
            assert mock.call_count == 1, "0.75 missing MUST trigger detail fetch (was <0.7 only before fix)"

    @pytest.mark.asyncio
    async def test_gate_085_missing_triggers_fetch(self):
        c = _cand("http://example.com/b", 0.85, None)
        connector = ConfigurableHtmlConnector("k", "http://example.com", VALID_CONFIG)
        with patch("app.connectors.common.fetch_httpx_text", new=AsyncMock(return_value=("http://example.com/b", GENERIC_DETAIL, "text/html"))) as mock:
            await connector._deep_fetch_candidates([c])
            assert mock.call_count == 1, "0.85 missing MUST trigger via OR funding_missing"

    @pytest.mark.asyncio
    async def test_gate_090_present_skips_fetch(self):
        c = _cand("http://example.com/c", 0.90, "$10,000 USD")
        connector = ConfigurableHtmlConnector("k", "http://example.com", VALID_CONFIG)
        with patch("app.connectors.common.fetch_httpx_text", new=AsyncMock(return_value=("http://example.com/c", GENERIC_DETAIL, "text/html"))) as mock:
            await connector._deep_fetch_candidates([c])
            assert mock.call_count == 0, "0.90 with funding present MUST skip"

    @pytest.mark.asyncio
    async def test_gate_072_present_still_triggers_via_conf(self):
        c = _cand("http://example.com/d", 0.72, "$5,000 USD")
        connector = ConfigurableHtmlConnector("k", "http://example.com", VALID_CONFIG)
        with patch("app.connectors.common.fetch_httpx_text", new=AsyncMock(return_value=("http://example.com/d", GENERIC_DETAIL, "text/html"))) as mock:
            await connector._deep_fetch_candidates([c])
            assert mock.call_count == 1, "conf<0.82 even with funding must still trigger"


class TestFundingMirror:
    """Requirement: _enrich_from_detail MUST extract funding_amount_raw mirroring GenericHtml."""

    @pytest.mark.asyncio
    async def test_enrich_from_detail_extracts_50m_cop(self):
        connector = ConfigurableHtmlConnector("k", "http://example.com", VALID_CONFIG)
        with patch("app.connectors.common.fetch_httpx_text", new=AsyncMock(return_value=("http://example.com/detail", DETAIL_WITH_FUNDING, "text/html"))):
            result = await connector._enrich_from_detail("http://example.com/detail")
            assert result is not None
            assert "funding_amount_raw" in result, "must mirror GenericHtml funding extraction (6-line mirror)"
            assert "50,000,000" in result["funding_amount_raw"] or "50000000" in result["funding_amount_raw"].replace(",", "").replace(".", "")

    @pytest.mark.asyncio
    async def test_deep_fetch_keeps_funding_when_present(self):
        """Detail without funding must not overwrite existing funding (keeps higher-confidence)."""
        c = _cand("http://example.com/e", 0.60, "$99,000 USD")
        connector = ConfigurableHtmlConnector("k", "http://example.com", VALID_CONFIG)
        no_funding_detail = "<html><body><h1>Detail No Funding</h1></body></html>"
        with patch("app.connectors.common.fetch_httpx_text", new=AsyncMock(return_value=("http://example.com/e", no_funding_detail, "text/html"))):
            enriched = await connector._deep_fetch_candidates([c])
            assert enriched[0].funding_amount_raw == "$99,000 USD"


class TestSemaphoreBound:
    """Requirement: Semaphore(25) per scrape run, 60 details → max 25 concurrent."""

    @pytest.mark.asyncio
    async def test_60_details_bounded_to_25(self, monkeypatch):
        # Temporarily raise detail limit so all 60 are considered for enrichment
        monkeypatch.setattr("app.connectors.configurable_html._detail_limit", lambda: 60)
        cands = [_cand(f"http://example.com/{i}", 0.5, None) for i in range(60)]
        connector = ConfigurableHtmlConnector("k", "http://example.com", VALID_CONFIG)

        concurrent = 0
        max_conc = 0
        lock = asyncio.Lock()

        async def _tracked(url, **kwargs):
            nonlocal concurrent, max_conc
            async with lock:
                concurrent += 1
                max_conc = max(max_conc, concurrent)
            await asyncio.sleep(0.02)
            async with lock:
                concurrent -= 1
            return (url, GENERIC_DETAIL, "text/html")

        with patch("app.connectors.common.fetch_httpx_text", new=AsyncMock(side_effect=_tracked)):
            result = await connector._deep_fetch_candidates(cands)

        assert max_conc <= 25, f"semaphore must bound to 25, observed {max_conc}"
        assert max_conc >= 2, "should have some concurrency"
        assert len(result) == 60


class TestMetricsGauges:
    def test_snapshot_exposes_throttle_gauges(self):
        from app.scraper import metrics
        metrics.reset()
        metrics.record_throttled(source_key="grants.gov", delay_s=1.5)
        snap = metrics.snapshot()
        assert "throttled_count" in snap
        assert snap["throttled_count"] == 1
        assert snap["delay_for_wait"] == 1.5
        assert "burst_utilization" in snap

    def test_config_flags_off_default(self):
        from app.core.config import get_settings
        get_settings.cache_clear()
        s = get_settings()
        assert s.extraction_batch_enabled is False
        assert s.extraction_spa_retry is False
        assert s.throttle_max_per_day == 150
        get_settings.cache_clear()
