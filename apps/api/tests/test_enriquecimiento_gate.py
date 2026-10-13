"""E25: detail-enrichment gate extension + Groq/LLM 429 backoff.

- Gate: ``ascun-convocatorias``, ``cost-open-calls`` and
  ``sdde-bogota-convocatorias`` join ``DETAIL_ENRICHMENT_PILOT_KEYS`` so the
  runner-level SSR batch enriches them; non-pilot keys still pass through
  untouched (zero network: the fetch helper is stubbed or asserted uncalled).
- Backoff: ``_call_llm`` retries 429 with exponential backoff (honouring
  ``Retry-After``) and degrades to the existing fallback (returns None, never
  raises) when 429 persists.

Strict TDD: tests written FIRST, implementation follows.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.connectors.base import OpportunityCandidate


def _candidate(url: str, **overrides) -> OpportunityCandidate:
    base = {
        "title": "Convocatoria piloto E25",
        "entity": "Entidad piloto",
        "country": "Colombia",
        "official_url": url,
        "summary": "Convocatoria piloto E25",
        "raw_text": "Convocatoria piloto E25",
        "confidence_score": 0.55,
    }
    base.update(overrides)
    return OpportunityCandidate(**base)


_DETAIL_HTML = """<html><body><main>
<h1>Convocatoria piloto E25</h1>
<div class="content">
<p>Fecha de cierre: 15/12/2026</p>
<p>Consulta los terminos de referencia en este portal.</p>
</div>
</main></body></html>"""


class TestGateE25:
    def test_gate_includes_new_keys(self):
        """RED E25: the three new sources join the pilot gate."""
        from app.connectors.common import DETAIL_ENRICHMENT_PILOT_KEYS

        assert "ascun-convocatorias" in DETAIL_ENRICHMENT_PILOT_KEYS
        assert "cost-open-calls" in DETAIL_ENRICHMENT_PILOT_KEYS
        assert "sdde-bogota-convocatorias" in DETAIL_ENRICHMENT_PILOT_KEYS

    def test_gate_pins_existing_keys(self):
        """Earlier pilots stay intact after the extension."""
        from app.connectors.common import DETAIL_ENRICHMENT_PILOT_KEYS

        for key in (
            "grants-gov",
            "minciencias",
            "innpulsa",
            "fapesp-brasil",
            "developmentaid-tenders",
            "secihti-mexico-ciencias",
            "universidad-nacional-colombia",
            "novo-nordisk-grants",
            "fondo-emprender-sena",
            "unitar-courses",
        ):
            assert key in DETAIL_ENRICHMENT_PILOT_KEYS

    @pytest.mark.asyncio
    async def test_novo_still_enriched(self, monkeypatch):
        """Pin: a gated source reaches the SSR batch (fetch called)."""
        from app.connectors.common import enrich_pilot_candidates

        mock_fetch = AsyncMock(
            return_value=("https://example.com/novo/grant-1", _DETAIL_HTML, "text/html")
        )
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock_fetch)

        (result,) = await enrich_pilot_candidates(
            "novo-nordisk-grants", [_candidate("https://example.com/novo/grant-1")]
        )

        assert result.close_date is not None
        mock_fetch.assert_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "source_key,url",
        [
            ("ascun-convocatorias", "https://example.com/ascun/conv-1"),
            ("cost-open-calls", "https://example.com/cost/call-1"),
            ("sdde-bogota-convocatorias", "https://example.com/sdde/conv-1"),
        ],
    )
    async def test_new_keys_enrich_through_ssr_batch(
        self, monkeypatch, source_key, url
    ):
        """RED E25: each new key enriches through the existing SSR batch path."""
        from app.connectors.common import enrich_pilot_candidates

        mock_fetch = AsyncMock(return_value=(url, _DETAIL_HTML, "text/html"))
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock_fetch)

        (result,) = await enrich_pilot_candidates(source_key, [_candidate(url)])

        assert result.close_date is not None
        assert (result.close_date.year, result.close_date.month, result.close_date.day) == (
            2026,
            12,
            15,
        )
        mock_fetch.assert_awaited()

    @pytest.mark.asyncio
    async def test_non_pilot_passes_through_without_fetch(self, monkeypatch):
        """Pin the mechanism: keys outside the gate get no detail fetch."""
        from app.connectors.common import enrich_pilot_candidates

        mock_fetch = AsyncMock()
        monkeypatch.setattr("app.connectors.common.fetch_httpx_text", mock_fetch)

        candidates = [_candidate("https://example.com/elsewhere/conv-1")]
        result = await enrich_pilot_candidates("some-unknown-source", candidates)

        assert result == candidates
        mock_fetch.assert_not_awaited()


def _groq_settings(**overrides):
    settings = MagicMock()
    settings.llm_api_key = "test-key"
    settings.llm_provider = "groq"
    settings.llm_api_base = "https://api.groq.com/openai/v1"
    settings.llm_timeout_seconds = 30
    settings.chat_model = "llama-3.3-70b-versatile"
    settings.llm_model = "llama-3.3-70b-versatile"
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


def _rate_limit_error(retry_after: str | None = None) -> httpx.HTTPStatusError:
    headers = {} if retry_after is None else {"retry-after": retry_after}
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(429, headers=headers, request=request)
    return httpx.HTTPStatusError("429 Too Many Requests", request=request, response=response)


def _ok_response() -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(
        return_value={"choices": [{"message": {"content": '{"title": "Test"}'}}]}
    )
    return response


class TestGroqBackoff:
    @pytest.mark.asyncio
    async def test_recovers_after_transient_429s(self, monkeypatch):
        """RED: 429 x2 then 200 succeeds via retry instead of dying."""
        from app.core.ai import _call_llm

        sleeps: list[float] = []

        async def _fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setattr("app.core.ai.asyncio.sleep", _fake_sleep)

        with patch("app.core.ai.http_client", new_callable=AsyncMock) as mock_http_client:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=[
                    _rate_limit_error(),
                    _rate_limit_error(),
                    _ok_response(),
                ]
            )
            mock_http_client.return_value = mock_client
            with patch("app.core.ai.get_settings", return_value=_groq_settings()):
                result = await _call_llm("test text")

        assert result is not None
        assert result.get("title") == "Test"
        assert mock_client.post.await_count == 3
        assert sleeps == [5.0, 15.0]

    @pytest.mark.asyncio
    async def test_persistent_429_degrades_to_fallback_without_raising(self, monkeypatch):
        """RED: endless 429 degrades to None (existing fallback), never raises."""
        from app.core.ai import _call_llm

        sleeps: list[float] = []

        async def _fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setattr("app.core.ai.asyncio.sleep", _fake_sleep)

        with patch("app.core.ai.http_client", new_callable=AsyncMock) as mock_http_client:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=_rate_limit_error())
            mock_http_client.return_value = mock_client
            with patch("app.core.ai.get_settings", return_value=_groq_settings()):
                result = await _call_llm("test text")  # must not raise

        assert result is None
        # Bounded: initial attempt + 3 retries, then give up (no infinite loop).
        assert mock_client.post.await_count == 4
        assert sleeps == [5.0, 15.0, 30.0]

    @pytest.mark.asyncio
    async def test_retry_after_header_is_honored(self, monkeypatch):
        """RED: a Retry-After header overrides the default backoff delay."""
        from app.core.ai import _call_llm

        sleeps: list[float] = []

        async def _fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setattr("app.core.ai.asyncio.sleep", _fake_sleep)

        with patch("app.core.ai.http_client", new_callable=AsyncMock) as mock_http_client:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=[_rate_limit_error(retry_after="1"), _ok_response()]
            )
            mock_http_client.return_value = mock_client
            with patch("app.core.ai.get_settings", return_value=_groq_settings()):
                result = await _call_llm("test text")

        assert result is not None
        assert sleeps == [1.0]

    @pytest.mark.asyncio
    async def test_non_429_errors_still_raise_to_existing_fallback(self):
        """Pin: non-429 failures keep the old raise-to-caller-fallback path."""
        from app.core.ai import _call_llm

        request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
        server_error = httpx.HTTPStatusError(
            "500 Internal Server Error",
            request=request,
            response=httpx.Response(500, request=request),
        )

        with patch("app.core.ai.http_client", new_callable=AsyncMock) as mock_http_client:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=server_error)
            mock_http_client.return_value = mock_client
            with patch("app.core.ai.get_settings", return_value=_groq_settings()):
                with pytest.raises(httpx.HTTPStatusError):
                    await _call_llm("test text")

        assert mock_client.post.await_count == 1
