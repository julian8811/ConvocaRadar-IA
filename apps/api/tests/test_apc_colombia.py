"""Per-source timeout bounds for apc-colombia.

Server evidence 2026-10-10: TimeoutError at the 180s per-source cap.
Diagnosis 2026-10-10 (1 respectful sequential pass over the 7 seed URLs):
6/7 pages answer 200 in <0.5s, but `?page=2` hangs at TLS handshake (>25s).
The connector fans out to 7 pages with 30s x retries=2 each plus a
Playwright render fallback queued on a single slot — one hanging page is
enough to blow the 180s cap. Fix: fail fast per page (15s, 1 attempt, no
render — Drupal SSR needs no browser); a failed page is skipped, the rest
still yield.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.connectors.apc_colombia import APC_URLS, ApcColombiaConnector
from app.connectors.base import RawSourceResult

APC_PAGE_HTML = """<html><body>
<article class="page teaser"><div class="az-text">
<h3>Convocatoria de cooperacion internacional 2026</h3>
<p>Abierta hasta el 30 de noviembre de 2026. Postulacion en linea.</p>
<a href="/modalidades-de-cooperacion/convocatorias/conv-001">Ver convocatoria de cooperacion</a>
</div></article>
</body></html>
"""


@pytest.fixture
def mock_fetch(monkeypatch) -> AsyncMock:
    mock = AsyncMock()
    monkeypatch.setattr("app.connectors.apc_colombia.fetch_httpx_text", mock)
    return mock


class TestApcFetchBounds:
    @pytest.mark.asyncio
    async def test_hanging_page_does_not_stall_connector(self, mock_fetch):
        """RED: one hanging page (like ?page=2) must fail fast; rest yield."""

        async def _side_effect(url, **kwargs):
            if "page=2" in url:
                raise RuntimeError("Timeout fetching after 15s (attempt 1/1)")
            return (url, APC_PAGE_HTML, "text/html")

        mock_fetch.side_effect = _side_effect
        connector = ApcColombiaConnector()

        result = await connector.fetch()

        assert isinstance(result, RawSourceResult)
        pages = result.metadata["pages"]
        assert len(pages) == len(APC_URLS) - 1
        # Every per-page call is bounded: 15s, single attempt, no render.
        for call in mock_fetch.await_args_list:
            assert call.kwargs.get("timeout_seconds") == 15
            assert call.kwargs.get("retries") == 1
            assert call.kwargs.get("playwright_fallback") is False

    @pytest.mark.asyncio
    async def test_single_source_last_resort_is_bounded(self, mock_fetch):
        """RED: the last-resort single fetch must carry the same bounds."""
        mock_fetch.side_effect = RuntimeError("all pages down")
        connector = ApcColombiaConnector()

        with pytest.raises(RuntimeError):
            await connector.fetch()

        assert mock_fetch.await_count == len(APC_URLS) + 1
        last = mock_fetch.await_args_list[-1]
        assert last.kwargs.get("timeout_seconds") == 15
        assert last.kwargs.get("retries") == 1
        assert last.kwargs.get("playwright_fallback") is False


class TestApcParseGuard:
    @pytest.mark.asyncio
    async def test_parse_yields_from_surviving_pages(self):
        """Triangulation: pages that survive still parse (no behavior change)."""
        connector = ApcColombiaConnector()
        raw = RawSourceResult(
            source_key="apc-colombia",
            url=APC_URLS[0],
            content=APC_PAGE_HTML,
            content_type="text/html",
            metadata={"pages": [{"url": APC_URLS[0], "content": APC_PAGE_HTML}]},
        )

        candidates = await connector.parse(raw)

        assert len(candidates) >= 1
        assert all("apccolombia.gov.co" in c.official_url for c in candidates)
