"""Resource-bound tests for GenericHtmlConnector URL resolution.

``_resolve_base_url`` walks up to ~40 candidate URLs (original, parent paths,
fallback patterns, homepage). Without a deadline, one broken base URL stalls
the whole source run on every attempt. The connector must give up after
``RESOLVE_URL_TIMEOUT`` seconds and fall back to the original base URL, and
its detail-page enrichment cap must match configurable_html's resource
posture (DEEP_FETCH_LIMIT).
"""

from __future__ import annotations

import asyncio
import time

import pytest

from app.connectors import generic_html as gh


def _always_fail_after(delay: float):
    async def _try_url(url, **kwargs):
        await asyncio.sleep(delay)
        return None

    return _try_url


class TestResolveBaseUrlDeadline:
    def test_gives_up_within_timeout_when_every_attempt_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(gh, "RESOLVE_URL_TIMEOUT", 0.2)  # absent pre-fix -> AttributeError (RED)
        conn = gh.GenericHtmlConnector("k", "https://example.com/a/b/c")
        conn._try_url = _always_fail_after(0.05)

        started = time.monotonic()
        resolved = asyncio.run(conn._resolve_base_url())
        elapsed = time.monotonic() - started

        assert resolved == "https://example.com/a/b/c"
        # ~40 candidates x 0.05s would need ~2s without the deadline bound.
        assert elapsed < 1.5

    def test_first_successful_url_returns_immediately(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        async def _try_url(url, **kwargs):
            calls.append(url)
            return (url, "<html></html>", "text/html")

        monkeypatch.setattr(gh, "RESOLVE_URL_TIMEOUT", 5)
        conn = gh.GenericHtmlConnector("k", "https://example.com/a/b/c")
        conn._try_url = _try_url

        assert asyncio.run(conn._resolve_base_url()) == "https://example.com/a/b/c"
        assert calls == ["https://example.com/a/b/c"]


class TestDeepFetchLimitAlignment:
    def test_matches_configurable_connector_limit(self) -> None:
        from app.connectors import configurable_html as ch

        assert gh.DEEP_FETCH_LIMIT == ch.DEEP_FETCH_LIMIT == 10
