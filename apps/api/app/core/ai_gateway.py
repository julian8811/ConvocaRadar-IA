"""T5 (fortalecer-201): gateway ordenado de embeddings IA.

Orden de proveedores: **Gemini (primario)** → remoto genérico compatible
(Codex/OpenAI vía ``llm_*``, solo si está configurado) → **hash-local**
(siempre disponible, sin credenciales).

- **Adapter**: cada proveedor implementa :class:`EmbeddingProvider`. Un futuro
  proveedor (DGX/vLLM) se agrega implementando el protocolo y anexándolo a
  :func:`ordered_providers` — sin tocar las llamadas.
- **Caché**: hash SHA-256 del texto normalizado (+ modelo y dims) → vector.
  En memoria del proceso, con TTL y tope LRU simple. Contenido idéntico no se
  re-embeddea (ni siquiera consume cuota).
- **Cuotas**: solo las llamadas REMOTAS consumen cuota por organización
  (ventanas día y mes rodante vía ``AI_QUOTA_EMBEDDINGS_PER_*``). Cuota
  excedida → degradación elegante a local con log + marca
  ``quota_exceeded`` en la traza (el path productivo nunca levanta; para
  rechazo duro existe :func:`check_embedding_quota`).
- **Trazabilidad**: cada llamada externa emite traza estructurada (proveedor,
  modelo, ``latency_ms``, tokens y costo USD estimados) vía structlog
  ``ai_gateway``. :meth:`AITrace.to_dict` está listo para persistirse en las
  columnas JSON existentes (``Task.result`` / ``AuditLog.metadata``) — sin
  migración Alembic.

Decisión de producto: Gemini es el primario y se configura con
``GEMINI_API_KEY``. Como alias (sin duplicar variables) se acepta
``LLM_API_KEY`` cuando ``LLM_PROVIDER=gemini``.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Protocol

import structlog

from app.core.ai import LOCAL_EMBEDDING_MODEL_VERSION, normalize_text
from app.core.config import effective_llm_provider, get_settings

logger = structlog.get_logger("ai_gateway")

# Costo estimado USD por 1K tokens (solo para operar gasto relativo, NO
# facturación). 0.0 = tier gratuito / self-hosted a la fecha de escritura.
COST_USD_PER_1K_TOKENS: dict[str, float] = {
    "text-embedding-004": 0.0,  # Gemini, tier gratuito
    "gemini-embedding-001": 0.0,  # Gemini, tier gratuito
    "text-embedding-3-small": 0.00002,
    "text-embedding-3-large": 0.00013,
}

# Mes rodante de 30 días fijos (suficiente para guardarraíl operativo).
_MONTH_SECONDS = 30 * 86400
_DAY_SECONDS = 86400


class QuotaExceededError(RuntimeError):
    """Cuota remota de embeddings excedida para una organización."""

    def __init__(self, organization_id: str, window: str, limit: int) -> None:
        super().__init__(f"AI quota exceeded org={organization_id} window={window} limit={limit}")
        self.organization_id = organization_id
        self.window = window
        self.limit = limit


@dataclass
class AITrace:
    """Traza de una llamada (o intento) del gateway."""

    provider: str
    model: str
    latency_ms: float
    estimated_tokens: int = 0
    estimated_cost_usd: float = 0.0
    cached: bool = False
    fallback_reason: str | None = None
    organization_id: str | None = None
    count: int = 1

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "latency_ms": round(self.latency_ms, 2),
            "estimated_tokens": self.estimated_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "cached": self.cached,
            "fallback_reason": self.fallback_reason,
            "organization_id": self.organization_id,
            "count": self.count,
        }


@dataclass
class GatewayEmbeddingResult:
    vectors: list[list[float]] = field(default_factory=list)
    providers: list[str] = field(default_factory=list)  # proveedor por texto
    models: list[str] = field(default_factory=list)  # modelo por texto
    cached: list[bool] = field(default_factory=list)
    traces: list[dict] = field(default_factory=list)

    @property
    def model_version(self) -> str:
        """Etiqueta de versión para filas ``OpportunityEmbedding``.

        Compatible con ``embedding_model_version()``: ``{prov}-{model}-d{dims}``
        en remoto, ``local-hash-embeddings-v2`` en local.
        """
        if not self.providers:
            return LOCAL_EMBEDDING_MODEL_VERSION
        provider, model = self.providers[0], self.models[0]
        if provider == "local":
            return LOCAL_EMBEDDING_MODEL_VERSION
        dims = len(self.vectors[0]) if self.vectors else 0
        return f"{provider}-{model}-d{dims}"


def estimate_tokens(text: str) -> int:
    """Aproximación barata (~4 chars/token) para operar gasto."""
    return max(1, len(text) // 4)


def estimate_cost_usd(model: str, tokens: int) -> float:
    return round(COST_USD_PER_1K_TOKENS.get(model, 0.0) * tokens / 1000, 6)


def resolve_gemini_api_key(settings=None) -> str | None:
    """Key efectiva de Gemini: ``GEMINI_API_KEY`` o alias ``LLM_API_KEY``."""
    settings = settings or get_settings()
    if getattr(settings, "gemini_api_key", None):
        return settings.gemini_api_key
    try:
        if effective_llm_provider(settings.llm_provider) == "gemini" and settings.llm_api_key:
            return settings.llm_api_key
    except ValueError:
        pass
    return None


# ── Caché en memoria ──────────────────────────────────────────────────

# key → (vector, provider, model, expira_en_monotonic)
_EMBED_CACHE: dict[str, tuple[list[float], str, str, float]] = {}
_EMBED_CACHE_ORDER: list[str] = []


def embedding_cache_key(text: str, *, provider_model: str, dimensions: int) -> str:
    normalized = normalize_text(text)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"{provider_model}|d{dimensions}|{digest}"


def _cache_settings() -> tuple[int, int]:
    settings = get_settings()
    try:
        size = max(1, int(settings.ai_embedding_cache_size))
    except Exception:
        size = 1024
    try:
        ttl = max(0, int(settings.ai_embedding_cache_ttl_seconds))
    except Exception:
        ttl = 86400
    return size, ttl


def cache_get(key: str) -> tuple[list[float], str, str] | None:
    entry = _EMBED_CACHE.get(key)
    if entry is None:
        return None
    vector, provider, model, expires = entry
    if expires < time.monotonic():
        _EMBED_CACHE.pop(key, None)
        try:
            _EMBED_CACHE_ORDER.remove(key)
        except ValueError:
            pass
        return None
    try:
        _EMBED_CACHE_ORDER.remove(key)
    except ValueError:
        pass
    _EMBED_CACHE_ORDER.append(key)
    return vector, provider, model


def cache_set(key: str, vector: list[float], provider: str, model: str) -> None:
    size, ttl = _cache_settings()
    if key in _EMBED_CACHE:
        try:
            _EMBED_CACHE_ORDER.remove(key)
        except ValueError:
            pass
    _EMBED_CACHE[key] = (vector, provider, model, time.monotonic() + ttl)
    _EMBED_CACHE_ORDER.append(key)
    while len(_EMBED_CACHE_ORDER) > size:
        oldest = _EMBED_CACHE_ORDER.pop(0)
        _EMBED_CACHE.pop(oldest, None)


def clear_embedding_cache() -> None:
    _EMBED_CACHE.clear()
    _EMBED_CACHE_ORDER.clear()


# ── Cuotas por organización (en memoria; se reinician con el proceso) ──

# org_id → [inicio_ventana_epoch, conteo]
_QUOTA_DAY: dict[str, list[float]] = {}
_QUOTA_MONTH: dict[str, list[float]] = {}


def reset_ai_quotas() -> None:
    _QUOTA_DAY.clear()
    _QUOTA_MONTH.clear()


def _check_window(
    store: dict[str, list[float]], org_id: str, limit: int, window_s: int, name: str
) -> None:
    if limit <= 0:  # <=0 = cuota deshabilitada (fail-open documentado)
        return
    now = time.time()
    start, count = store.get(org_id, [now, 0])
    if now - start >= window_s:
        start, count = now, 0
        store[org_id] = [start, count]
    if count >= limit:
        raise QuotaExceededError(org_id, name, limit)


def _record_window(store: dict[str, list[float]], org_id: str, n: int, window_s: int) -> None:
    now = time.time()
    start, count = store.get(org_id, [now, 0])
    if now - start >= window_s:
        start, count = now, 0
    store[org_id] = [start, count + n]


def check_embedding_quota(organization_id: str | None) -> None:
    """Rechazo duro si la org excede día o mes. ``None`` = sin cuota."""
    if organization_id is None:
        return
    settings = get_settings()
    _check_window(_QUOTA_DAY, organization_id, int(settings.ai_quota_embeddings_per_day), _DAY_SECONDS, "day")
    _check_window(
        _QUOTA_MONTH, organization_id, int(settings.ai_quota_embeddings_per_month), _MONTH_SECONDS, "month"
    )


def record_embedding_usage(organization_id: str | None, n: int = 1) -> None:
    if organization_id is None or n <= 0:
        return
    settings = get_settings()
    if int(settings.ai_quota_embeddings_per_day) > 0:
        _record_window(_QUOTA_DAY, organization_id, n, _DAY_SECONDS)
    if int(settings.ai_quota_embeddings_per_month) > 0:
        _record_window(_QUOTA_MONTH, organization_id, n, _MONTH_SECONDS)


# ── Proveedores (adapter) ─────────────────────────────────────────────


class EmbeddingProvider(Protocol):
    name: str

    @property
    def model(self) -> str: ...

    def is_configured(self) -> bool: ...

    async def embed(self, texts: list[str], *, dimensions: int) -> list[list[float]] | None: ...


async def _post_embeddings_openai_compatible(
    *, base: str, api_key: str, model: str, texts: list[str], timeout: int
) -> list[list[float]] | None:
    """POST ``{base}/embeddings`` OpenAI-compatible. None si no sirve."""
    from app.core.http_client import http_client

    client = await http_client()
    response = await client.post(
        f"{base.rstrip('/')}/embeddings",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "input": [t[:8000] for t in texts]},
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    rows = data.get("data") or []
    if not rows:
        return None
    try:
        rows = sorted(rows, key=lambda r: r.get("index", 0))
    except Exception:
        pass
    vectors: list[list[float]] = []
    for row in rows:
        vec = row.get("embedding")
        if isinstance(vec, list):
            vectors.append([round(float(v), 6) for v in vec])
    if len(vectors) != len(texts):
        return None
    return vectors


class LocalHashEmbeddingProvider:
    """Fallback hash-local: siempre configurado, sin credenciales ni red."""

    name = "local"

    @property
    def model(self) -> str:
        return LOCAL_EMBEDDING_MODEL_VERSION

    def is_configured(self) -> bool:
        return True

    async def embed(self, texts: list[str], *, dimensions: int) -> list[list[float]]:
        from app.core.ai import build_local_hash_vector

        return [build_local_hash_vector(t, dimensions) for t in texts]


class GeminiEmbeddingProvider:
    """Primario comercial: Gemini vía endpoint OpenAI-compatible."""

    name = "gemini"

    @property
    def model(self) -> str:
        return get_settings().gemini_embedding_model

    def is_configured(self) -> bool:
        return resolve_gemini_api_key() is not None

    async def embed(self, texts: list[str], *, dimensions: int) -> list[list[float]] | None:
        settings = get_settings()
        api_key = resolve_gemini_api_key(settings)
        if not api_key:
            return None
        vectors = await _post_embeddings_openai_compatible(
            base=settings.gemini_api_base,
            api_key=api_key,
            model=settings.gemini_embedding_model,
            texts=texts,
            timeout=settings.llm_timeout_seconds,
        )
        if vectors is None:
            return None
        # Gemini devuelve dims fijas del modelo; si no coinciden con las del
        # índice, no se puede usar (el scoring exige igual longitud).
        if any(len(v) != dimensions for v in vectors):
            logger.warning(
                "gemini_dimension_mismatch",
                expected=dimensions,
                got=len(vectors[0]) if vectors else 0,
                model=settings.gemini_embedding_model,
            )
            return None
        return vectors


class GenericRemoteEmbeddingProvider:
    """Secundario opcional (Codex/OpenAI-compatible vía ``llm_*``).

    Reusa el batch con retry ya probado de ``services.embeddings``; solo
    activo si hay key + modelo configurados. Sin key → se omite en silencio.
    """

    @property
    def name(self) -> str:
        try:
            return effective_llm_provider(get_settings().llm_provider)
        except ValueError:
            return "remote"

    @property
    def model(self) -> str:
        return get_settings().embedding_model

    def is_configured(self) -> bool:
        try:
            settings = get_settings()
            return (
                effective_llm_provider(settings.llm_provider) != "local"
                and bool(settings.llm_api_key)
                and bool(settings.embedding_model)
            )
        except ValueError:
            return False

    async def embed(self, texts: list[str], *, dimensions: int) -> list[list[float]] | None:
        from app.services.embeddings import (
            EMBEDDING_BATCH_RETRY_CHUNK,
            EMBEDDING_BATCH_SIZE,
            _call_openai_embedding_batch,
        )

        out: list[list[float] | None] = [None] * len(texts)
        for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            chunk_idx = list(range(i, min(i + EMBEDDING_BATCH_SIZE, len(texts))))
            chunk = [texts[j] for j in chunk_idx]
            try:
                batch = await _call_openai_embedding_batch(chunk, dimensions=dimensions)
            except Exception:
                batch = None
            if batch is not None and len(batch) == len(chunk):
                for j, vec in zip(chunk_idx, batch):
                    out[j] = vec
                continue
            # Reintento en sub-chunks (semántica heredada del batch legacy).
            for k in range(0, len(chunk), EMBEDDING_BATCH_RETRY_CHUNK):
                sub_idx = chunk_idx[k : k + EMBEDDING_BATCH_RETRY_CHUNK]
                sub = [texts[j] for j in sub_idx]
                try:
                    sub_batch = await _call_openai_embedding_batch(sub, dimensions=dimensions)
                except Exception:
                    sub_batch = None
                if sub_batch is not None and len(sub_batch) == len(sub):
                    for j, vec in zip(sub_idx, sub_batch):
                        out[j] = vec
        # Todo-o-nada: si algún texto quedó sin vector remoto, el gateway
        # degrada el lote completo a local (nunca cachea vectores vacíos).
        if any(v is None for v in out):
            return None
        return [v for v in out if v is not None]


def ordered_providers() -> list[EmbeddingProvider]:
    """Cadena en orden de preferencia. Para agregar DGX/vLLM: anexar aquí."""
    return [
        GeminiEmbeddingProvider(),
        GenericRemoteEmbeddingProvider(),
        LocalHashEmbeddingProvider(),
    ]


def resolve_primary_provider(settings=None) -> EmbeddingProvider:
    """Primer proveedor configurado (local siempre lo está)."""
    settings = settings or get_settings()
    if GeminiEmbeddingProvider().is_configured():
        return GeminiEmbeddingProvider()
    generic = GenericRemoteEmbeddingProvider()
    # is_configured lee settings globales; suficiente (mismo proceso).
    if generic.is_configured():
        return generic
    return LocalHashEmbeddingProvider()


def _primary_model_label(settings=None) -> tuple[str, str]:
    primary = resolve_primary_provider(settings)
    return primary.name, primary.model


# ── Entrada principal ─────────────────────────────────────────────────


async def embed_texts(
    texts: list[str], *, dimensions: int | None = None, organization_id: str | None = None
) -> GatewayEmbeddingResult:
    """Embeddings vía gateway ordenado con caché, cuotas y trazabilidad.

    Nunca levanta por fallos remotos: degrada a hash-local y lo marca en la
    traza. Sin llamadas reales cuando todo está cacheado o en local.
    """
    result = GatewayEmbeddingResult()
    if not texts:
        return result
    settings = get_settings()
    target = dimensions or settings.embedding_dimensions or 64

    # 1) Caché por (modelo primario, dims, texto normalizado).
    primary_name, primary_model = _primary_model_label(settings)
    pending_idx: list[int] = []
    for i, text in enumerate(texts):
        key = embedding_cache_key(text, provider_model=primary_model, dimensions=target)
        hit = cache_get(key)
        if hit is not None:
            vector, provider, model = hit
            result.vectors.append(vector)
            result.providers.append(provider)
            result.models.append(model)
            result.cached.append(True)
        else:
            result.vectors.append([])
            result.providers.append("")
            result.models.append("")
            result.cached.append(False)
            pending_idx.append(i)
    if pending_idx:
        result.traces.append(
            AITrace(
                provider=primary_name,
                model=primary_model,
                latency_ms=0.0,
                cached=True,
                organization_id=organization_id,
                count=len(texts) - len(pending_idx),
            ).to_dict()
        )
    if not pending_idx:
        return result

    # 2) Cuota (solo importa si el primario es remoto).
    quota_exceeded = False
    if organization_id is not None and primary_name != "local":
        try:
            check_embedding_quota(organization_id)
        except QuotaExceededError as exc:
            quota_exceeded = True
            logger.warning("ai_quota_exceeded", org=exc.organization_id, window=exc.window, limit=exc.limit)

    # 3) Cadena de proveedores para los pendientes.
    pending_texts = [texts[i] for i in pending_idx]
    served: list[list[float]] | None = None
    served_by = ""
    served_model = ""
    fallback_reason: str | None = "quota_exceeded" if quota_exceeded else None

    if not quota_exceeded:
        for provider in ordered_providers():
            if provider.name == "local":
                continue
            if not provider.is_configured():
                continue
            started = time.perf_counter()
            try:
                vectors = await provider.embed(pending_texts, dimensions=target)
            except Exception as exc:  # un proveedor no debe tumbar al resto
                logger.warning("ai_provider_failed", provider=provider.name, error=str(exc)[:200])
                fallback_reason = f"{provider.name}_error"
                continue
            latency_ms = (time.perf_counter() - started) * 1000
            if vectors is None or len(vectors) != len(pending_texts):
                fallback_reason = f"{provider.name}_bad_response"
                continue
            tokens = sum(estimate_tokens(t) for t in pending_texts)
            trace = AITrace(
                provider=provider.name,
                model=provider.model,
                latency_ms=latency_ms,
                estimated_tokens=tokens,
                estimated_cost_usd=estimate_cost_usd(provider.model, tokens),
                organization_id=organization_id,
                count=len(pending_texts),
            )
            result.traces.append(trace.to_dict())
            logger.info("ai_embedding_call", **trace.to_dict())
            record_embedding_usage(organization_id, len(pending_texts))
            served, served_by, served_model = vectors, provider.name, provider.model
            fallback_reason = None
            break
            # Nota: si el primario remoto falló pero hay otro remoto
            # configurado, el loop ya lo intenta (orden de la cadena).

    if served is None:
        started = time.perf_counter()
        local = LocalHashEmbeddingProvider()
        served = await local.embed(pending_texts, dimensions=target)
        latency_ms = (time.perf_counter() - started) * 1000
        served_by, served_model = local.name, local.model
        trace = AITrace(
            provider=served_by,
            model=served_model,
            latency_ms=latency_ms,
            estimated_tokens=sum(estimate_tokens(t) for t in pending_texts),
            estimated_cost_usd=0.0,
            fallback_reason=fallback_reason,
            organization_id=organization_id,
            count=len(pending_texts),
        )
        result.traces.append(trace.to_dict())
        logger.info("ai_embedding_call", **trace.to_dict())

    for i, vector in zip(pending_idx, served):
        result.vectors[i] = vector
        result.providers[i] = served_by
        result.models[i] = served_model
        key = embedding_cache_key(texts[i], provider_model=served_model, dimensions=target)
        cache_set(key, vector, served_by, served_model)
    return result
