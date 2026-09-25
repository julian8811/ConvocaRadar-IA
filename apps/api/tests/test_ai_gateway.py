"""T5 (fortalecer-201): gateway IA — orden, caché, cuotas y trazabilidad.

Sin llamadas reales a APIs: todo remoto va mockeado (http_client o provider).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _isolate_gateway():
    from app.core import ai_gateway as gw

    gw.clear_embedding_cache()
    gw.reset_ai_quotas()
    yield
    gw.clear_embedding_cache()
    gw.reset_ai_quotas()


def _local_env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("LLM_PROVIDER", "local")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("EMBEDDING_MODEL", "")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


def _mock_http_post(monkeypatch: pytest.MonkeyPatch, vectors: list[list[float]], calls: list) -> None:
    async def _fake_post(*args, **kwargs):
        payload = kwargs.get("json") or {}
        calls.append(payload)
        inputs = payload.get("input") or []
        vecs = [vectors[i % len(vectors)] for i in range(len(inputs))]
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json = MagicMock(
            return_value={"data": [{"index": i, "embedding": v} for i, v in enumerate(vecs)]}
        )
        return response

    client = AsyncMock()
    client.post = AsyncMock(side_effect=_fake_post)
    monkeypatch.setattr("app.core.http_client.http_client", AsyncMock(return_value=client))


async def test_gemini_is_primary_when_key_present(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import ai_gateway as gw

    _local_env(monkeypatch, GEMINI_API_KEY="g-test")
    posted: list = []
    _mock_http_post(monkeypatch, [[0.5, 0.5]], posted)
    with patch.object(
        gw.GenericRemoteEmbeddingProvider, "embed", new=AsyncMock(side_effect=AssertionError("must not be called"))
    ):
        result = await gw.embed_texts(["beca investigación"], dimensions=2)
    assert result.providers == ["gemini"]
    assert result.vectors == [[0.5, 0.5]]
    assert len(posted) == 1
    assert posted[0]["model"] == "text-embedding-004"


async def test_fallback_to_local_without_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import ai_gateway as gw
    from app.core.ai import build_embedding

    _local_env(monkeypatch)
    result = await gw.embed_texts(["convocatoria local"], dimensions=8)
    assert result.providers == ["local"]
    expected = await build_embedding("convocatoria local", dimensions=8)
    assert result.vectors[0] == expected


async def test_fallback_to_local_when_gemini_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import ai_gateway as gw

    _local_env(monkeypatch, GEMINI_API_KEY="g-test")

    async def _boom(*args, **kwargs):
        raise RuntimeError("gemini down")

    client = AsyncMock()
    client.post = AsyncMock(side_effect=_boom)
    monkeypatch.setattr("app.core.http_client.http_client", AsyncMock(return_value=client))

    result = await gw.embed_texts(["texto"], dimensions=4)
    assert result.providers == ["local"]
    assert len(result.vectors[0]) == 4
    reasons = [t.get("fallback_reason") for t in result.traces]
    assert any(r and "gemini" in r for r in reasons)


async def test_cache_hit_avoids_second_call(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import ai_gateway as gw

    _local_env(monkeypatch, GEMINI_API_KEY="g-test")
    posted: list = []
    _mock_http_post(monkeypatch, [[0.1, 0.2]], posted)
    first = await gw.embed_texts(["texto repetido"], dimensions=2)
    second = await gw.embed_texts(["texto  repetido"], dimensions=2)  # normaliza igual
    assert len(posted) == 1
    assert first.vectors == second.vectors
    assert second.cached == [True]


async def test_generic_remote_is_secondary_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con key genérica (Codex) y sin Gemini: se usa el remoto legacy."""
    from app.core import ai_gateway as gw

    _local_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("EMBEDDING_MODEL", "bge-m3")
    from app.core.config import get_settings

    get_settings.cache_clear()
    with patch(
        "app.services.embeddings._call_openai_embedding_batch",
        new=AsyncMock(return_value=[[0.3] * 4]),
    ) as mock_batch:
        result = await gw.embed_texts(["hola"], dimensions=4, organization_id="org-1")
    assert result.providers == ["openai"]
    mock_batch.assert_awaited_once()
    assert result.traces[-1]["estimated_tokens"] >= 1


async def test_quota_exceeded_degrades_to_local(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import ai_gateway as gw
    from app.core.config import get_settings

    _local_env(monkeypatch, GEMINI_API_KEY="g-test", AI_QUOTA_EMBEDDINGS_PER_DAY="2")
    get_settings.cache_clear()
    posted: list = []
    _mock_http_post(monkeypatch, [[0.9, 0.9]], posted)

    first = await gw.embed_texts(["uno", "dos"], dimensions=2, organization_id="org-q")
    assert first.providers == ["gemini", "gemini"]
    second = await gw.embed_texts(["tres"], dimensions=2, organization_id="org-q")
    assert second.providers == ["local"]
    assert any(t.get("fallback_reason") == "quota_exceeded" for t in second.traces)
    assert len(posted) == 1  # el excedente no pegó a la red

    with pytest.raises(gw.QuotaExceededError):
        gw.check_embedding_quota("org-q")


async def test_trace_carries_provider_latency(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import ai_gateway as gw

    _local_env(monkeypatch)
    result = await gw.embed_texts(["trazar"], dimensions=4, organization_id="org-t")
    assert result.traces, "debe emitir al menos una traza"
    trace = result.traces[-1]
    for field in ("provider", "model", "latency_ms", "estimated_tokens", "estimated_cost_usd"):
        assert field in trace, f"falta {field} en traza"
    assert trace["provider"] == "local"
    assert trace["latency_ms"] >= 0


async def test_trace_dict_persists_in_task_result_json() -> None:
    """La traza es JSON-plano: entra en Task.result sin migración."""
    from app.core.ai_gateway import AITrace

    trace = AITrace(provider="gemini", model="text-embedding-004", latency_ms=12.5).to_dict()
    import json

    payload = {"ai_calls": [trace]}
    assert json.loads(json.dumps(payload))["ai_calls"][0]["provider"] == "gemini"


async def test_gemini_alias_via_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_PROVIDER=gemini + LLM_API_KEY configura Gemini sin GEMINI_API_KEY."""
    from app.core import ai_gateway as gw

    _local_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_API_KEY", "alias-key")
    from app.core.config import get_settings

    get_settings.cache_clear()
    assert gw.resolve_gemini_api_key() == "alias-key"
    assert gw.GeminiEmbeddingProvider().is_configured()


async def test_adapter_chain_is_extensible(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un futuro proveedor (DGX/vLLM) entra anexándolo a ordered_providers."""
    from app.core import ai_gateway as gw

    _local_env(monkeypatch)

    class DgxProvider:
        name = "dgx"

        @property
        def model(self) -> str:
            return "dgx-embed-1"

        def is_configured(self) -> bool:
            return True

        async def embed(self, texts: list[str], *, dimensions: int):
            return [[1.0] * dimensions for _ in texts]

    real_ordered = gw.ordered_providers
    monkeypatch.setattr(gw, "ordered_providers", lambda: [DgxProvider(), gw.LocalHashEmbeddingProvider()])
    monkeypatch.setattr(gw, "resolve_primary_provider", lambda settings=None: DgxProvider())
    result = await gw.embed_texts(["futuro"], dimensions=3)
    assert result.providers == ["dgx"]
    assert result.vectors == [[1.0, 1.0, 1.0]]
    assert real_ordered  # la cadena original sigue intacta
