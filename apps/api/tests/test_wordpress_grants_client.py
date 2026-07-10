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

        with patch("app.connectors.wordpress_grants.http_client", new_callable=AsyncMock) as mock_http_client:
            mock_client = AsyncMock()
            # First request returns a page with 1 item, then empty to stop pagination
            page1_response = AsyncMock()
            page1_response.json = MagicMock(return_value=[{"id": 1, "title": "Grant 1", "status": "publish"}])
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

        with patch("app.connectors.wordpress_grants.http_client", new_callable=AsyncMock) as mock_http_client:
            mock_client = AsyncMock()
            page1_response = AsyncMock()
            page1_response.json = MagicMock(return_value=[{"id": 1, "title": "Grant 1", "status": "publish"}])
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
