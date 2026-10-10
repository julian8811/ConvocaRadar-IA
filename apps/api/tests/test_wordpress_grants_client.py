"""Tests that WordPressGrantsConnector uses the global HTTPX client.

Strict TDD: tests written FIRST, implementation follows.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


class TestWordPressGrantsConnectorUsesGlobalClient:
    """RED: WordPressGrantsConnector.fetch should use http_client() singleton."""

    async def test_fetch_uses_http_client(self) -> None:
        """fetch() should call http_client() and make requests via the global client."""
        from app.connectors.wordpress_grants import WordPressGrantsConnector

        connector = WordPressGrantsConnector(
            source_key="test-wp",
            base_url="https://test.example.com/wp-json/wp/v2/posts",
            entity_name="Test Source",
        )

        with patch(
            "app.connectors.wordpress_grants.http_client", new_callable=AsyncMock
        ) as mock_http_client:
            mock_client = AsyncMock()
            # First request returns a page with 1 item, then empty to stop pagination
            page1_response = AsyncMock()
            page1_response.json = MagicMock(
                return_value=[{"id": 1, "title": "Grant 1", "status": "publish"}]
            )
            page1_response.headers = {"X-WP-TotalPages": "1"}
            page1_response.raise_for_status = MagicMock()
            page1_response.url = "https://test.example.com/wp-json/wp/v2/posts?page=1"

            empty_response = AsyncMock()
            empty_response.json = MagicMock(return_value=[])
            empty_response.headers = {}
            empty_response.raise_for_status = MagicMock()
            empty_response.url = "https://test.example.com/wp-json/wp/v2/posts?page=2"

            mock_client.get = AsyncMock(side_effect=[page1_response, empty_response])
            mock_http_client.return_value = mock_client

            result = await connector.fetch()

        # Verify http_client() was called
        mock_http_client.assert_awaited_once()
        # Verify client.get was called at least once
        assert mock_client.get.await_count >= 1
        # Verify result
        assert result.source_key == "test-wp"

    async def test_fetch_does_not_create_own_client(self) -> None:
        """fetch() should NOT construct its own httpx.AsyncClient."""
        from app.connectors.wordpress_grants import WordPressGrantsConnector

        connector = WordPressGrantsConnector(
            source_key="test-wp",
            base_url="https://test.example.com/wp-json/wp/v2/posts",
            entity_name="Test Source",
        )

        with patch(
            "app.connectors.wordpress_grants.http_client", new_callable=AsyncMock
        ) as mock_http_client:
            mock_client = AsyncMock()
            page1_response = AsyncMock()
            page1_response.json = MagicMock(
                return_value=[{"id": 1, "title": "Grant 1", "status": "publish"}]
            )
            page1_response.headers = {"X-WP-TotalPages": "1"}
            page1_response.raise_for_status = MagicMock()
            page1_response.url = "https://test.example.com/wp-json/wp/v2/posts?page=1"

            empty_response = AsyncMock()
            empty_response.json = MagicMock(return_value=[])
            empty_response.headers = {}
            empty_response.raise_for_status = MagicMock()

            mock_client.get = AsyncMock(side_effect=[page1_response, empty_response])
            mock_http_client.return_value = mock_client

            with patch("httpx.AsyncClient") as mock_async_client:
                result = await connector.fetch()

            # httpx.AsyncClient should NOT have been constructed
            mock_async_client.assert_not_called()

        assert result.source_key == "test-wp"


class TestWordPressMaxPages:
    """Per-source page cap: novo-nordisk-grants times out at 180s with up to
    10 sequential 15s pages. Evidence 2026-10-10: Total=136, TotalPages=2 —
    a cap of 3 covers 300 items. cost-eu keeps the legacy 10."""

    async def _run_fetch(self, max_pages, total_pages_header="10", pages_available=10):
        from app.connectors.wordpress_grants import WordPressGrantsConnector

        connector = WordPressGrantsConnector(
            source_key="test-wp",
            base_url="https://test.example.com/wp-json/wp/v2/grant",
            entity_name="Test Source",
            max_pages=max_pages,
        )
        with patch(
            "app.connectors.wordpress_grants.http_client", new_callable=AsyncMock
        ) as mock_http_client:
            mock_client = AsyncMock()

            def _page_response(page):
                resp = AsyncMock()
                resp.json = MagicMock(
                    return_value=[{"id": page, "title": f"Grant {page}", "status": "publish"}]
                )
                resp.headers = {"X-WP-TotalPages": total_pages_header}
                resp.raise_for_status = MagicMock()
                resp.url = f"https://test.example.com/wp-json/wp/v2/grant?page={page}"
                return resp

            mock_client.get = AsyncMock(
                side_effect=[_page_response(p) for p in range(1, pages_available + 1)]
            )
            mock_http_client.return_value = mock_client
            result = await connector.fetch()
        return mock_client, result

    async def test_max_pages_caps_requests(self) -> None:
        """RED: max_pages=3 with TotalPages=10 -> exactly 3 requests."""
        mock_client, result = await self._run_fetch(max_pages=3)
        assert mock_client.get.await_count == 3
        assert result.metadata["items_fetched"] == 3

    async def test_default_preserves_legacy_ten(self) -> None:
        """Triangulation: no max_pages -> legacy behavior (up to 10)."""
        mock_client, _ = await self._run_fetch(max_pages=None)
        assert mock_client.get.await_count == 10

    async def test_stops_early_when_fewer_pages(self) -> None:
        """Triangulation: TotalPages=2 stops at 2 even with max_pages=3."""
        mock_client, result = await self._run_fetch(
            max_pages=3, total_pages_header="2", pages_available=3
        )
        assert mock_client.get.await_count == 2
        assert result.metadata["items_fetched"] == 2

    def test_factory_gives_novo_page_cap(self) -> None:
        from app.connectors.factory import connector_for

        connector = connector_for(
            "novo-nordisk-grants",
            "https://novonordiskfonden.dk/wp-json/wp/v2/grant?per_page=100&status=publish",
        )
        assert connector.max_pages == 3

    def test_factory_keeps_legacy_cap_for_other_wp(self) -> None:
        from app.connectors.factory import connector_for

        connector = connector_for(
            "cost-eu", "https://www.cost.eu/wp-json/wp/v2/pages"
        )
        assert connector.max_pages == 10
