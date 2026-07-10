"""Tests for the global HTTPX client singleton (app.core.http_client).

Strict TDD: tests written FIRST, before the module exists.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

pytestmark = pytest.mark.asyncio


class TestHttpClientCreation:
    """RED: Test that http_client() returns a functional AsyncClient singleton."""

    async def test_http_client_returns_async_client(self) -> None:
        """http_client() should return an httpx.AsyncClient instance."""
        from app.core.http_client import http_client

        client = await http_client()
        assert isinstance(client, httpx.AsyncClient)

    async def test_http_client_is_singleton(self) -> None:
        """Multiple calls to http_client() should return the same instance."""
        from app.core.http_client import http_client

        client1 = await http_client()
        client2 = await http_client()
        assert client1 is client2

    async def test_sync_client_returns_sync_client(self) -> None:
        """sync_http_client() should return an httpx.Client instance."""
        from app.core.http_client import sync_http_client

        client = sync_http_client()
        assert isinstance(client, httpx.Client)

    async def test_sync_client_is_singleton(self) -> None:
        """Multiple calls to sync_http_client() should return the same instance."""
        from app.core.http_client import sync_http_client

        client1 = sync_http_client()
        client2 = sync_http_client()
        assert client1 is client2


class TestHttpClientClose:
    """RED: Test that close functions work correctly."""

    async def test_close_async_client_does_not_raise(self) -> None:
        """close_async_client() should not raise, even on first call."""
        from app.core.http_client import close_async_client

        # Should not raise when called before any client was created
        await close_async_client()

    async def test_close_async_client_idempotent(self) -> None:
        """close_async_client() should be safe to call multiple times."""
        from app.core.http_client import http_client, close_async_client

        await http_client()  # initialize
        await close_async_client()
        await close_async_client()  # second call should be safe

    async def test_close_sync_client_does_not_raise(self) -> None:
        """close_sync_client() should not raise, even on first call."""
        from app.core.http_client import close_sync_client

        close_sync_client()

    async def test_close_sync_client_idempotent(self) -> None:
        """close_sync_client() should be safe to call multiple times."""
        from app.core.http_client import sync_http_client, close_sync_client

        sync_http_client()  # initialize
        close_sync_client()
        close_sync_client()  # second call should be safe


class TestHttpClientLifespanIntegration:
    """Test that the FastAPI lifespan initializes & closes the global clients.

    Uses TestClient to trigger real lifespan events (startup + shutdown).
    """

    async def test_lifespan_startup_initializes_async_client(self) -> None:
        """Using TestClient as context manager triggers lifespan → http_client() is callable."""
        from app.core.http_client import close_async_client, close_sync_client, http_client
        from app.main import app
        from fastapi.testclient import TestClient

        # Ensure clean state
        await close_async_client()
        close_sync_client()

        with TestClient(app) as _client:
            # Lifespan startup ran; client should be usable
            client = await http_client()
            assert isinstance(client, httpx.AsyncClient)
            assert not client.is_closed

        # Lifespan shutdown ran; client should be closed
        assert client.is_closed

    async def test_lifespan_startup_initializes_sync_client(self) -> None:
        """sync_http_client() should work after lifespan startup."""
        from app.core.http_client import close_async_client, close_sync_client, sync_http_client
        from app.main import app
        from fastapi.testclient import TestClient

        await close_async_client()
        close_sync_client()

        with TestClient(app) as _client:
            client = sync_http_client()
            assert isinstance(client, httpx.Client)
            assert not client.is_closed

        # After shutdown the sync client should be closed
        assert client.is_closed


class TestUrlIsReachableUsesSyncClient:
    """RED: url_is_reachable should use sync_http_client() singleton."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self) -> None:
        """Clear the lru_cache on url_is_reachable before each test."""
        import app.services as services_mod

        services_mod.url_is_reachable.cache_clear()

    async def test_url_is_reachable_calls_sync_http_client(self) -> None:
        """url_is_reachable() should delegate to sync_http_client(), not create its own."""
        import app.services as services_mod

        from app.core.http_client import close_sync_client

        close_sync_client()

        with patch("app.services.sync_http_client") as mock_sync_client:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.head.return_value = mock_response
            mock_sync_client.return_value = mock_client

            with patch("app.services.is_public_http_url", return_value=True):
                result = services_mod.url_is_reachable("https://example.com/alpha")

        assert result is True
        mock_sync_client.assert_called_once()
        mock_client.head.assert_called_once()

    async def test_url_is_reachable_does_not_create_own_client(self) -> None:
        """url_is_reachable() should NOT construct its own httpx.Client."""
        import app.services as services_mod

        from app.core.http_client import close_sync_client

        close_sync_client()

        with patch("app.services.sync_http_client") as mock_sync_client:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.head.return_value = mock_response
            mock_sync_client.return_value = mock_client

            with patch("app.services.is_public_http_url", return_value=True):
                with patch("httpx.Client") as mock_httpx_client:
                    result = services_mod.url_is_reachable("https://example.com/beta")

            mock_httpx_client.assert_not_called()

        assert result is True

    async def test_url_is_reachable_returns_false_for_405(self) -> None:
        """When server returns 405, url_is_reachable should fall back to GET."""
        import app.services as services_mod

        from app.core.http_client import close_sync_client

        close_sync_client()

        with patch("app.services.sync_http_client") as mock_sync_client:
            mock_client = MagicMock()
            # HEAD returns 405 → fall back to GET
            mock_head_response = MagicMock()
            mock_head_response.status_code = 405
            mock_get_response = MagicMock()
            mock_get_response.status_code = 200
            mock_client.head.return_value = mock_head_response
            mock_client.get.return_value = mock_get_response
            mock_sync_client.return_value = mock_client

            with patch("app.services.is_public_http_url", return_value=True):
                result = services_mod.url_is_reachable("https://example.com/gamma")

        assert result is True
        mock_client.head.assert_called_once()
        mock_client.get.assert_called_once()


class TestFetchHttpxTextUsesGlobalClient:
    """RED: fetch_httpx_text should use http_client() singleton."""

    async def test_fetch_httpx_text_uses_http_client(self) -> None:
        """fetch_httpx_text() should delegate to http_client(), not create its own."""
        from app.core.http_client import close_async_client
        from app.connectors.common import fetch_httpx_text

        await close_async_client()

        with patch("app.connectors.common.http_client", new_callable=AsyncMock) as mock_http_client:
            mock_client = AsyncMock()
            mock_response = AsyncMock()
            mock_response.text = "response body"
            mock_response.headers = {"content-type": "text/html"}
            mock_response.raise_for_status = MagicMock()
            mock_response.url = "https://example.com/result"
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_http_client.return_value = mock_client

            with patch("app.connectors.common._is_private_host", return_value=False):
                url, text, content_type = await fetch_httpx_text(
                    "https://example.com/test",
                    headers={"X-Custom": "value"},
                )

        mock_http_client.assert_awaited_once()
        mock_client.request.assert_awaited_once()
        assert text == "response body"

    async def test_fetch_httpx_text_does_not_create_own_client(self) -> None:
        """fetch_httpx_text() should NOT construct its own httpx.AsyncClient."""
        from app.core.http_client import close_async_client
        from app.connectors.common import fetch_httpx_text

        await close_async_client()

        with patch("app.connectors.common.http_client", new_callable=AsyncMock) as mock_http_client:
            mock_client = AsyncMock()
            mock_response = AsyncMock()
            mock_response.text = "response body"
            mock_response.headers = {"content-type": "text/html"}
            mock_response.raise_for_status = MagicMock()
            mock_response.url = "https://example.com/result"
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_http_client.return_value = mock_client

            with patch("app.connectors.common._is_private_host", return_value=False):
                with patch("httpx.AsyncClient") as mock_async_client:
                    await fetch_httpx_text(
                        "https://example.com/test",
                        headers={"X-Custom": "value"},
                    )

            mock_async_client.assert_not_called()


class TestFetchHttpxBytesUsesGlobalClient:
    """RED: fetch_httpx_bytes should use http_client() singleton."""

    async def test_fetch_httpx_bytes_uses_http_client(self) -> None:
        """fetch_httpx_bytes() should delegate to http_client(), not create its own."""
        from app.core.http_client import close_async_client
        from app.connectors.common import fetch_httpx_bytes

        await close_async_client()

        with patch("app.connectors.common.http_client", new_callable=AsyncMock) as mock_http_client:
            mock_client = AsyncMock()
            mock_response = AsyncMock()
            mock_response.content = b"binary data"
            mock_response.headers = {"content-type": "application/pdf"}
            mock_response.raise_for_status = MagicMock()
            mock_response.url = "https://example.com/doc"
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_http_client.return_value = mock_client

            with patch("app.connectors.common._is_private_host", return_value=False):
                url, data, content_type = await fetch_httpx_bytes(
                    "https://example.com/doc",
                )

        mock_http_client.assert_awaited_once()
        mock_client.request.assert_awaited_once()
        assert data == b"binary data"

    async def test_fetch_httpx_bytes_does_not_create_own_client(self) -> None:
        """fetch_httpx_bytes() should NOT construct its own httpx.AsyncClient."""
        from app.core.http_client import close_async_client
        from app.connectors.common import fetch_httpx_bytes

        await close_async_client()

        with patch("app.connectors.common.http_client", new_callable=AsyncMock) as mock_http_client:
            mock_client = AsyncMock()
            mock_response = AsyncMock()
            mock_response.content = b"binary data"
            mock_response.headers = {"content-type": "application/pdf"}
            mock_response.raise_for_status = MagicMock()
            mock_response.url = "https://example.com/doc"
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_http_client.return_value = mock_client

            with patch("app.connectors.common._is_private_host", return_value=False):
                with patch("httpx.AsyncClient") as mock_async_client:
                    await fetch_httpx_bytes(
                        "https://example.com/doc",
                    )

            mock_async_client.assert_not_called()


class TestHttpClientAfterClose:
    """RED: After close, getting a client should create a fresh one."""

    async def test_async_client_reinitializes_after_close(self) -> None:
        """After close_async_client(), http_client() should create a new instance."""
        from app.core.http_client import http_client, close_async_client

        client_a = await http_client()
        await close_async_client()
        client_b = await http_client()
        assert client_b is not client_a
        assert isinstance(client_b, httpx.AsyncClient)

    async def test_sync_client_reinitializes_after_close(self) -> None:
        """After close_sync_client(), sync_http_client() should create a new instance."""
        from app.core.http_client import sync_http_client, close_sync_client

        client_a = sync_http_client()
        close_sync_client()
        client_b = sync_http_client()
        assert client_b is not client_a
        assert isinstance(client_b, httpx.Client)
