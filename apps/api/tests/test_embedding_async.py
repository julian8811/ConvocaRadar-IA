"""Tests for async build_embedding and build_embedding_sync bridge.

Strict TDD: tests written FIRST, implementation follows.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestBuildEmbeddingAsync:
    """RED: build_embedding should be async and await _call_openai_embedding."""

    @pytest.mark.asyncio
    async def test_build_embedding_uses_openai_when_configured(self) -> None:
        """build_embedding should call _call_openai_embedding when LLM is configured."""
        from app.core.ai import build_embedding

        with patch("app.core.ai._call_openai_embedding", new_callable=AsyncMock) as mock_openai:
            mock_openai.return_value = [0.1, 0.2, 0.3]

            with patch("app.core.ai.get_settings") as mock_settings:
                settings = mock_settings.return_value
                settings.llm_provider = "openai"
                settings.llm_api_key = "test-key"
                settings.embedding_model = "text-embedding-3-small"
                settings.embedding_dimensions = 3

                result = await build_embedding("test text", dimensions=3)

        mock_openai.assert_awaited_once_with("test text", dimensions=3)
        assert result == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_build_embedding_falls_back_to_hash_when_no_llm(self) -> None:
        """build_embedding should fall back to hash embedding when no LLM is configured."""
        from app.core.ai import build_embedding

        with patch("app.core.ai._call_openai_embedding", new_callable=AsyncMock) as mock_openai:
            mock_openai.return_value = None  # Simulate no LLM

            with patch("app.core.ai.get_settings") as mock_settings:
                settings = mock_settings.return_value
                settings.llm_provider = "local"
                settings.llm_api_key = None
                settings.embedding_model = None
                settings.embedding_dimensions = 4

                result = await build_embedding("hello world", dimensions=4)

        # _call_openai_embedding should NOT be called when provider is not openai
        mock_openai.assert_not_called()
        assert len(result) == 4
        # Hash embedding should produce a unit vector
        magnitude = sum(v * v for v in result) ** 0.5
        assert abs(magnitude - 1.0) < 0.001

    @pytest.mark.asyncio
    async def test_build_embedding_falls_back_on_http_error(self) -> None:
        """build_embedding should fall back to hash when _call_openai_embedding raises."""
        from app.core.ai import build_embedding

        with patch("app.core.ai._call_openai_embedding", new_callable=AsyncMock) as mock_openai:
            mock_openai.side_effect = Exception("HTTP error")

            with patch("app.core.ai.get_settings") as mock_settings:
                settings = mock_settings.return_value
                settings.llm_provider = "openai"
                settings.llm_api_key = "test-key"
                settings.embedding_model = "text-embedding-3-small"
                settings.embedding_dimensions = 4

                result = await build_embedding("hello world", dimensions=4)

        mock_openai.assert_awaited_once()
        assert len(result) == 4
        # Hash embedding produces a unit vector
        magnitude = sum(v * v for v in result) ** 0.5
        assert abs(magnitude - 1.0) < 0.001

    @pytest.mark.asyncio
    async def test_build_embedding_hash_is_deterministic(self) -> None:
        """Hash embedding should produce the same output for the same input."""
        from app.core.ai import build_embedding

        with patch("app.core.ai._call_openai_embedding", new_callable=AsyncMock) as mock_openai:
            mock_openai.return_value = None  # Force hash fallback

            with patch("app.core.ai.get_settings") as mock_settings:
                settings = mock_settings.return_value
                settings.llm_provider = "local"
                settings.llm_api_key = None
                settings.embedding_model = None
                settings.embedding_dimensions = 8

                result1 = await build_embedding("deterministic text", dimensions=8)
                result2 = await build_embedding("deterministic text", dimensions=8)

        assert result1 == result2

    @pytest.mark.asyncio
    async def test_build_embedding_default_dimensions_from_settings(self) -> None:
        """When dimensions is None, should use settings.embedding_dimensions."""
        from app.core.ai import build_embedding

        with patch("app.core.ai._call_openai_embedding", new_callable=AsyncMock) as mock_openai:
            mock_openai.return_value = None

            with patch("app.core.ai.get_settings") as mock_settings:
                settings = mock_settings.return_value
                settings.llm_provider = "local"
                settings.llm_api_key = None
                settings.embedding_model = None
                settings.embedding_dimensions = 16  # default from settings

                result = await build_embedding("text")

        assert len(result) == 16


class TestBuildEmbeddingSyncBridge:
    """RED: build_embedding_sync should wrap async build_embedding."""

    def test_build_embedding_sync_returns_same_type(self) -> None:
        """build_embedding_sync should return a list[float]."""
        from app.core.ai import build_embedding_sync

        with patch("app.core.ai.get_settings") as mock_settings:
            settings = mock_settings.return_value
            settings.llm_provider = "local"
            settings.llm_api_key = None
            settings.embedding_model = None
            settings.embedding_dimensions = 4

            result = build_embedding_sync("hello sync", dimensions=4)

        assert isinstance(result, list)
        assert all(isinstance(v, float) for v in result)
        assert len(result) == 4

    def test_build_embedding_sync_matches_async_output(self) -> None:
        """build_embedding_sync should produce the same result as await build_embedding."""
        from app.core.ai import build_embedding, build_embedding_sync

        with patch("app.core.ai.get_settings") as mock_settings:
            settings = mock_settings.return_value
            settings.llm_provider = "local"
            settings.llm_api_key = None
            settings.embedding_model = None
            settings.embedding_dimensions = 4

            sync_result = build_embedding_sync("same text", dimensions=4)

            import asyncio
            async_result = asyncio.run(build_embedding("same text", dimensions=4))

        assert sync_result == async_result

    def test_build_embedding_sync_does_not_raise(self) -> None:
        """build_embedding_sync should never raise, just like the async version."""
        from app.core.ai import build_embedding_sync

        with patch("app.core.ai.get_settings") as mock_settings:
            settings = mock_settings.return_value
            settings.llm_provider = "local"
            settings.llm_api_key = None
            settings.embedding_model = None
            settings.embedding_dimensions = 4

            # Should not raise
            result = build_embedding_sync("")
            assert isinstance(result, list)


class TestCallOpenaiEmbeddingUsesGlobalClient:
    """RED: _call_openai_embedding should use http_client() singleton."""

    @pytest.mark.asyncio
    async def test_call_openai_embedding_uses_http_client(self) -> None:
        """_call_openai_embedding should use the global http_client()."""
        from app.core.ai import _call_openai_embedding

        from app.core.http_client import close_async_client

        await close_async_client()

        with patch("app.core.ai.http_client", new_callable=AsyncMock) as mock_http_client:
            mock_client = AsyncMock()
            mock_response = AsyncMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json = MagicMock(
                return_value={
                    "data": [{"embedding": [0.1, 0.2, 0.3]}]
                }
            )
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_http_client.return_value = mock_client

            with patch("app.core.ai.get_settings") as mock_settings:
                settings = mock_settings.return_value
                settings.llm_provider = "openai"
                settings.llm_api_key = "test-key"
                settings.embedding_model = "text-embedding-3-small"
                settings.llm_api_base = "https://api.openai.com/v1"
                settings.llm_timeout_seconds = 30

                result = await _call_openai_embedding("test text", dimensions=3)

        mock_http_client.assert_awaited_once()
        mock_client.post.assert_awaited_once()
        assert result == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_call_openai_embedding_does_not_create_own_client(self) -> None:
        """_call_openai_embedding should NOT construct its own httpx.AsyncClient."""
        from app.core.ai import _call_openai_embedding

        from app.core.http_client import close_async_client

        await close_async_client()

        with patch("app.core.ai.http_client", new_callable=AsyncMock) as mock_http_client:
            mock_client = AsyncMock()
            mock_response = AsyncMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json = MagicMock(
                return_value={
                    "data": [{"embedding": [0.1, 0.2, 0.3]}]
                }
            )
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_http_client.return_value = mock_client

            with patch("app.core.ai.get_settings") as mock_settings:
                settings = mock_settings.return_value
                settings.llm_provider = "openai"
                settings.llm_api_key = "test-key"
                settings.embedding_model = "text-embedding-3-small"
                settings.llm_api_base = "https://api.openai.com/v1"
                settings.llm_timeout_seconds = 30

                with patch("httpx.AsyncClient") as mock_async_client:
                    result = await _call_openai_embedding("test text", dimensions=3)

            mock_async_client.assert_not_called()

        assert result == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_call_openai_embedding_returns_none_on_no_data(self) -> None:
        """_call_openai_embedding should return None when API returns no data."""
        from app.core.ai import _call_openai_embedding

        with patch("app.core.ai.http_client", new_callable=AsyncMock) as mock_http_client:
            mock_client = AsyncMock()
            mock_response = AsyncMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json = MagicMock(return_value={"data": []})
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_http_client.return_value = mock_client

            with patch("app.core.ai.get_settings") as mock_settings:
                settings = mock_settings.return_value
                settings.llm_provider = "openai"
                settings.llm_api_key = "test-key"
                settings.embedding_model = "text-embedding-3-small"
                settings.llm_api_base = "https://api.openai.com/v1"
                settings.llm_timeout_seconds = 30

                result = await _call_openai_embedding("test text", dimensions=3)

        assert result is None
