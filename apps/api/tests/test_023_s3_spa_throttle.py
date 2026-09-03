"""S3 SPA+Throttle RED->GREEN - shell detector (thin+no-h1+ct+0+allowlist) + burst150."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, patch
from app.connectors.base import RawSourceResult

SHELL = "<html><head></head><body><div id='root'></div><script src='/app.js'></script></body></html>"
WITH_H1 = "<html><body><h1>T</h1><p>content</p></body></html>"
REAL = "<html><body><h1>Opportunities</h1>" + "x"*9000 + "</body></html>"

class TestShellDetector:
    def test_thin_no_h1_zero_true(self):
        from app.connectors.common import is_shell_response
        assert is_shell_response(SHELL, "text/html", 0) is True
    def test_with_h1_false(self):
        from app.connectors.common import is_shell_response
        assert is_shell_response(WITH_H1, "text/html", 0) is False
    def test_with_cands_false(self):
        from app.connectors.common import is_shell_response
        assert is_shell_response(SHELL, "text/html", 3) is False
    def test_json_ct_false(self):
        from app.connectors.common import is_shell_response
        assert is_shell_response(SHELL, "application/json", 0) is False
    def test_not_thin_false(self):
        from app.connectors.common import is_shell_response
        assert is_shell_response(REAL, "text/html", 0) is False
    def test_charset_true(self):
        from app.connectors.common import is_shell_response
        assert is_shell_response(SHELL, "text/html; charset=utf-8", 0) is True

class TestMaybeRetry:
    @pytest.mark.asyncio
    async def test_grants_gov_triggers(self):
        from app.connectors.common import maybe_retry_shell_with_pw
        with patch("app.connectors.common.get_settings") as ms:
            ms.return_value.extraction_spa_retry=True
            with patch("app.connectors.common.render_page_html", new_callable=AsyncMock) as mp:
                mp.return_value=("https://www.grants.gov/search-grants","<html><body><h1>Grants</h1></body></html>","text/html")
                r=await maybe_retry_shell_with_pw(content=SHELL,content_type="text/html",candidates=0,source_key="grants-gov",url="https://www.grants.gov/search-grants")
                assert mp.call_count==1 and r is not None
    @pytest.mark.asyncio
    async def test_simpler_triggers(self):
        from app.connectors.common import maybe_retry_shell_with_pw
        with patch("app.connectors.common.get_settings") as ms:
            ms.return_value.extraction_spa_retry=True
            with patch("app.connectors.common.render_page_html", new_callable=AsyncMock) as mp:
                mp.return_value=("https://simpler.grants.gov/search","<html><body><h1>OK</h1></body></html>","text/html")
                r=await maybe_retry_shell_with_pw(content=SHELL,content_type="text/html",candidates=0,source_key="simpler-grants",url="https://simpler.grants.gov/search")
                assert mp.call_count==1
    @pytest.mark.asyncio
    async def test_not_allowlist_no_retry(self):
        from app.connectors.common import maybe_retry_shell_with_pw
        with patch("app.connectors.common.get_settings") as ms:
            ms.return_value.extraction_spa_retry=True
            with patch("app.connectors.common.render_page_html", new_callable=AsyncMock) as mp:
                r=await maybe_retry_shell_with_pw(content=SHELL,content_type="text/html",candidates=0,source_key="minciencias",url="https://minciencias.gov.co/convocatorias")
                mp.assert_not_called(); assert r is None
    @pytest.mark.asyncio
    async def test_flag_false_no_retry(self):
        from app.connectors.common import maybe_retry_shell_with_pw
        with patch("app.connectors.common.get_settings") as ms:
            ms.return_value.extraction_spa_retry=False
            with patch("app.connectors.common.render_page_html", new_callable=AsyncMock) as mp:
                r=await maybe_retry_shell_with_pw(content=SHELL,content_type="text/html",candidates=0,source_key="grants-gov",url="https://www.grants.gov/search-grants")
                mp.assert_not_called(); assert r is None
    @pytest.mark.asyncio
    async def test_non_shell_no_retry(self):
        from app.connectors.common import maybe_retry_shell_with_pw
        with patch("app.connectors.common.get_settings") as ms:
            ms.return_value.extraction_spa_retry=True
            with patch("app.connectors.common.render_page_html", new_callable=AsyncMock) as mp:
                r=await maybe_retry_shell_with_pw(content=REAL,content_type="text/html",candidates=0,source_key="grants-gov",url="https://www.grants.gov/search-grants")
                mp.assert_not_called(); assert r is None
    @pytest.mark.asyncio
    async def test_cands_present_no_retry(self):
        from app.connectors.common import maybe_retry_shell_with_pw
        with patch("app.connectors.common.get_settings") as ms:
            ms.return_value.extraction_spa_retry=True
            with patch("app.connectors.common.render_page_html", new_callable=AsyncMock) as mp:
                r=await maybe_retry_shell_with_pw(content=SHELL,content_type="text/html",candidates=5,source_key="grants-gov",url="https://www.grants.gov/search-grants")
                mp.assert_not_called(); assert r is None

class TestThrottleBurst:
    def test_burst150_and_gauge(self):
        from app.scraper.domain_budget import DomainBudgetManager
        from app.scraper import metrics
        metrics.reset(); m=DomainBudgetManager()
        for _ in range(150): m.record_request("https://grants.gov/api")
        assert m.burst_exceeded("https://grants.gov/api") is True
        assert m.acquire("https://grants.gov/api") is False or m.throttle_max_per_day_exceeded("https://grants.gov/api") is True
        m.handle_429("https://grants.gov/api","5"); s=metrics.snapshot()
        assert s["throttled_count"]>=1 and "burst_utilization" in s
    def test_daily_cap_queue_gauge(self):
        from app.scraper.domain_budget import DomainBudgetManager
        from app.scraper import metrics
        metrics.reset(); m=DomainBudgetManager()
        for _ in range(150): m.record_request("https://example.com/a")
        d=m.handle_429("https://example.com/a","10")
        assert 1.0 <= d <= 60.0
        s=metrics.snapshot(); assert s["delay_for_wait"]>=1.0 or s["throttled_count"]>=1
    def test_playwright_slot_one(self):
        from app.scraper.domain_budget import DomainBudgetManager
        m=DomainBudgetManager(); assert m._max_concurrent_for("playwright")==1
        assert m.acquire("playwright") is True and m.acquire("playwright") is False
        m.release("playwright"); assert m.acquire("playwright") is True

class TestWiring:
    @pytest.mark.asyncio
    async def test_simpler_shell_calls_retry(self):
        from app.connectors.simpler_grants import SimplerGrantsConnector
        raw=RawSourceResult(source_key="simpler-grants",url="https://simpler.grants.gov/search",content=SHELL,content_type="text/html")
        with patch("app.connectors.common.get_settings") as ms:
            ms.return_value.extraction_spa_retry=True
            with patch("app.connectors.simpler_grants.maybe_retry_shell_with_pw", new_callable=AsyncMock) as mr:
                mr.return_value=("https://simpler.grants.gov/search","<html><body><h1>OK</h1></body></html>","text/html")
                conn=SimplerGrantsConnector(); await conn.parse(raw); assert mr.call_count==1
    @pytest.mark.asyncio
    async def test_grants_gov_shell_calls_retry(self):
        from app.connectors.grants_gov import GrantsGovConnector
        raw=RawSourceResult(source_key="grants-gov",url="https://www.grants.gov/search-grants",content=SHELL,content_type="text/html")
        with patch("app.connectors.common.get_settings") as ms:
            ms.return_value.extraction_spa_retry=True
            with patch("app.connectors.grants_gov.maybe_retry_shell_with_pw", new_callable=AsyncMock) as mr:
                mr.return_value=("https://www.grants.gov/search-grants","<html><body><h1>After PW</h1></body></html>","text/html")
                with patch("app.connectors.simpler_grants.SimplerGrantsConnector.parse", new_callable=AsyncMock) as sp:
                    sp.return_value=[]; conn=GrantsGovConnector(); await conn.parse(raw); assert mr.call_count>=1
