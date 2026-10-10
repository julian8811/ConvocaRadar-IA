"""Per-source timeout bounds for ascun-convocatorias.

Server evidence 2026-10-10: TimeoutError at the 180s per-source cap.
Diagnosis 2026-10-10 (1 respectful fetch): the WP REST query answers 200
in ~3.4s / 174KB — healthy. The slow phase is the unbounded client config:
default 120s x retries=2 plus a Playwright render fallback that can never
help a JSON API. Fix: 20s (6x headroom), single attempt, no render.
Worst case drops from >400s to ~20s.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.connectors.ascun import AscunConnector
from app.connectors.base import RawSourceResult

ASCUN_API_ITEMS = [
    {
        "id": 1,
        "date": "2026-09-01T10:00:00",
        "link": "https://ascun.org.co/convocatoria-becas-2026/",
        "title": {"rendered": "Convocatoria nacional de becas de investigacion 2026"},
        "excerpt": {"rendered": "<p>Becas para movilidad academica.</p>"},
        "content": {"rendered": "<p>Detalle de la convocatoria.</p>"},
    },
    {
        "id": 2,
        "date": "2026-09-02T10:00:00",
        "link": "https://ascun.org.co/red-universitaria-2026/",
        "title": {"rendered": "Red universitaria: encuentro de cooperacion"},
        "excerpt": {"rendered": ""},
        "content": {"rendered": "<p>Encuentro anual.</p>"},
    },
]


@pytest.fixture
def mock_fetch(monkeypatch) -> AsyncMock:
    mock = AsyncMock()
    monkeypatch.setattr("app.connectors.ascun.fetch_httpx_text", mock)
    return mock


class TestAscunFetchBounds:
    @pytest.mark.asyncio
    async def test_fetch_is_bounded_without_render(self, mock_fetch):
        """RED: single JSON call must be short, single-attempt, render-free."""
        mock_fetch.return_value = ("https://ascun.org.co/x", "[]", "application/json")
        connector = AscunConnector()

        await connector.fetch()

        mock_fetch.assert_awaited_once()
        call = mock_fetch.await_args_list[0]
        assert "search=convocatoria" in call.args[0]
        assert call.kwargs.get("timeout_seconds") == 20
        assert call.kwargs.get("retries") == 1
        assert call.kwargs.get("playwright_fallback") is False


class TestAscunParseGuard:
    @pytest.mark.asyncio
    async def test_parse_yields_from_api_items(self):
        """Triangulation: parse behavior unchanged (2 items -> 2 cands)."""
        connector = AscunConnector()
        raw = RawSourceResult(
            source_key="ascun-convocatorias",
            url="https://ascun.org.co/wp-json/wp/v2/posts?search=convocatoria",
            content=json.dumps(ASCUN_API_ITEMS),
            content_type="application/json",
        )

        candidates = await connector.parse(raw)

        assert len(candidates) == 2
        assert all("ascun.org.co" in c.official_url for c in candidates)

    @pytest.mark.asyncio
    async def test_parse_rejects_garbage(self):
        connector = AscunConnector()
        raw = RawSourceResult(
            source_key="ascun-convocatorias",
            url="https://ascun.org.co/wp-json/wp/v2/posts",
            content="<html>not json</html>",
            content_type="text/html",
        )

        assert await connector.parse(raw) == []
