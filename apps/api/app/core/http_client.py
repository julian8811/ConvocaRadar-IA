"""Global HTTPX client singletons for connection pooling.

Provides ``http_client()`` (async) and ``sync_http_client()`` (sync) — both
are lazily-initialized module-level singletons protected by a lock for thread
safety. Call ``close_async_client()`` and ``close_sync_client()`` during
FastAPI lifespan shutdown to release connections gracefully.
"""
from __future__ import annotations

import threading

import httpx

from app.core.config import get_settings

_lock = threading.Lock()
_client: httpx.Client | None = None
_async_client: httpx.AsyncClient | None = None


def sync_http_client() -> httpx.Client:
    """Return the global sync HTTPX client (lazily initialized, singleton).

    Thread-safe: uses ``threading.Lock`` to protect the check-then-act
    initialization path.  All callers — FastAPI thread-pool handlers, the
    background scheduler, CLI scripts — share the same singleton.
    """
    global _client
    if _client is None:
        with _lock:
            if _client is None:  # double-checked locking
                settings = get_settings()
                _client = httpx.Client(
                    timeout=settings.scraping_timeout_seconds or 30,
                    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
                    headers={"User-Agent": getattr(settings, "scraping_user_agent", "ConvocaRadarBot/0.1")},
                )
    return _client


def close_sync_client() -> None:
    """Close and release the global sync HTTPX client, if created.

    Intended for application shutdown.  Call from a sync context or wrap
    in ``asyncio.to_thread()`` when called from an async lifespan handler.
    """
    global _client
    if _client is not None:
        _client.close()
        _client = None


async def http_client() -> httpx.AsyncClient:
    """Return the global async HTTPX client (lazily initialized, singleton)."""
    global _async_client
    if _async_client is None:
        settings = get_settings()
        _async_client = httpx.AsyncClient(
            timeout=settings.scraping_timeout_seconds or 30,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            headers={"User-Agent": getattr(settings, "scraping_user_agent", "ConvocaRadarBot/0.1")},
        )
    return _async_client


async def close_async_client() -> None:
    """Close and release the global async HTTPX client, if created."""
    global _async_client
    if _async_client is not None:
        await _async_client.aclose()
        _async_client = None
