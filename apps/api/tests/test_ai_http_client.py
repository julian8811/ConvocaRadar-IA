"""Tests that _call_llm and other AI functions use the global HTTPX client.

Strict TDD: tests written FIRST, implementation follows.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


class TestCallLlmUsesGlobalClient:
    """RED: _call_llm should use the global http_client() singleton."""

    async def test_call_llm_uses_http_client_from_module(self) -> None:
        """_call_llm should call http_client() and post via the returned client."""
        from app.core.ai import _call_llm

        from app.core.http_client import close_async_client

        # Ensure clean state
        await close_async_client()

        with patch("app.core.ai.http_client", new_callable=AsyncMock) as mock_http_client:
            mock_client = AsyncMock()
            mock_response = AsyncMock()
            mock_response.raise_for_status = MagicMock()
            # httpx.Response.json() is a sync method, not async
            mock_response.json = MagicMock(
                return_value={"choices": [{"message": {"content": '{"title": "Test"}'}}]}
            )
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_http_client.return_value = mock_client

            with patch("app.core.ai.get_settings") as mock_settings:
                settings = mock_settings.return_value
                settings.llm_api_key = "test-key"
                settings.llm_provider = "openai"
                settings.llm_api_base = "https://api.openai.com/v1"
                settings.llm_timeout_seconds = 30
                settings.chat_model = "gpt-4"

                result = await _call_llm("test text")

        # Verify http_client() was called (not a new httpx.AsyncClient constructed)
        mock_http_client.assert_awaited_once()
        # Verify client.post was called with the right timeout override
        mock_client.post.assert_awaited_once()
        _, kwargs = mock_client.post.call_args
        assert kwargs.get("timeout") == 30

        # Verify the result
        assert result is not None
        assert result.get("title") == "Test"

    async def test_call_llm_does_not_create_own_client(self) -> None:
        """_call_llm should NOT construct its own httpx.AsyncClient."""
        from app.core.ai import _call_llm

        from app.core.http_client import close_async_client

        await close_async_client()

        with patch("app.core.ai.http_client", new_callable=AsyncMock) as mock_http_client:
            mock_client = AsyncMock()
            mock_response = AsyncMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json = MagicMock(
                return_value={"choices": [{"message": {"content": '{"title": "Test"}'}}]}
            )
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_http_client.return_value = mock_client

            with patch("app.core.ai.get_settings") as mock_settings:
                settings = mock_settings.return_value
                settings.llm_api_key = "test-key"
                settings.llm_provider = "openai"
                settings.llm_api_base = "https://api.openai.com/v1"
                settings.llm_timeout_seconds = 30
                settings.chat_model = "gpt-4"

                with patch("httpx.AsyncClient") as mock_async_client:
                    result = await _call_llm("test text")

            # httpx.AsyncClient should NOT have been constructed
            mock_async_client.assert_not_called()

        assert result is not None
        assert result.get("title") == "Test"
