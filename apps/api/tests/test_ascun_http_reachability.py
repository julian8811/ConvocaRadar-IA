"""Regression tests for source-specific ASCUN URL verification.

ASCUN server HEAD can take >5 s while GET works in about 4.5 s.
We stream GET response headers without downloading full news articles.
"""

import httpx
import pytest

from app.services import validation


@pytest.mark.asyncio
async def test_ascun_uses_streamed_get_not_head(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, text="ok")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        async def fake_client():
            return client

        monkeypatch.setattr("app.core.http_client.http_client", fake_client)
        validation._clear_url_cache()
        url = "https://ascun.org.co/noticias-ies/academic-story/"
        assert await validation.async_url_is_reachable(url)
        assert len(requests) == 1
        assert requests[0].method == "GET"
        assert requests[0].url.host == "ascun.org.co"
        validation._clear_url_cache()


@pytest.mark.asyncio
async def test_ascun_real_404_is_not_treated_as_alive(monkeypatch):
    methods = []

    def handler(request):
        methods.append(request.method)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        async def fake_client():
            return client

        monkeypatch.setattr("app.core.http_client.http_client", fake_client)
        validation._clear_url_cache()
        assert not await validation.async_url_is_reachable(
            "https://www.ascun.org.co/removed-page/"
        )
        assert methods == ["GET"]
        validation._clear_url_cache()


@pytest.mark.asyncio
async def test_unrelated_hosts_keep_previous_head_behavior(monkeypatch):
    methods = []

    def handler(request):
        methods.append(request.method)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        async def fake_client():
            return client

        monkeypatch.setattr("app.core.http_client.http_client", fake_client)
        validation._clear_url_cache()
        assert await validation.async_url_is_reachable(
            "https://example.org/opportunity/"
        )
        assert methods == ["HEAD"]
        validation._clear_url_cache()


@pytest.mark.asyncio
async def test_impostor_hostname_does_not_bypass_head(monkeypatch):
    methods = []

    def handler(request):
        methods.append(request.method)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        async def fake_client():
            return client

        monkeypatch.setattr("app.core.http_client.http_client", fake_client)
        validation._clear_url_cache()
        assert await validation.async_url_is_reachable(
            "https://ascun.org.co.example.org/noticias-ies/fake"
        )
        assert methods == ["HEAD"]
        validation._clear_url_cache()
