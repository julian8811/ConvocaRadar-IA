"""Global HTTPX client singletons for connection pooling.

Provides ``http_client()`` (async) and ``sync_http_client()`` (sync) — both
are lazily-initialized module-level singletons protected by a lock for thread
safety. Call ``close_async_client()`` and ``close_sync_client()`` during
FastAPI lifespan shutdown to release connections gracefully.

Event-loop safety
-----------------
``http_client()`` tracks which event loop created the singleton (during
lifespan / the main loop). When called from a **different** event loop
(notably ``execute_source_run_locally`` which creates a dedicated loop via
``asyncio.new_event_loop()``), it creates a **per-loop** client instead of
reusing the singleton.  Use ``close_per_loop_client()`` inside the secondary
loop to release those connections.
"""
from __future__ import annotations

import asyncio
import threading

import httpx

from app.core.config import get_settings

_lock = threading.Lock()
_client: httpx.Client | None = None
_async_client: httpx.AsyncClient | None = None
_async_client_loop_id: int | None = None
_secondary_clients: dict[int, httpx.AsyncClient] = {}


def _build_async_client() -> httpx.AsyncClient:
    """Build a fresh ``httpx.AsyncClient`` using current settings."""
    settings = get_settings()
    return httpx.AsyncClient(
        timeout=settings.scraping_timeout_seconds or 30,
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        headers={"User-Agent": getattr(settings, "scraping_user_agent", "ConvocaRadarBot/0.1")},
    )


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
    """Return the global async HTTPX client (lazily initialized, singleton).

    **Event-loop safety**: if the current running loop differs from the one
    that created the singleton (e.g. ``execute_source_run_locally``), a
    dedicated per-loop client is created and cached.  Call
    ``close_per_loop_client()`` from the secondary loop to release it.
    """
    global _async_client, _async_client_loop_id
    current_loop_id = id(asyncio.get_running_loop())

    # First call ever — initialise the singleton in whatever loop we are in.
    if _async_client is None:
        _async_client = _build_async_client()
        _async_client_loop_id = current_loop_id
        return _async_client

    # Same loop as the singleton — share the connection pool.
    if current_loop_id == _async_client_loop_id:
        return _async_client

    # Different loop — create / return a per-loop client.
    if current_loop_id not in _secondary_clients:
        _secondary_clients[current_loop_id] = _build_async_client()
    return _secondary_clients[current_loop_id]


async def close_per_loop_client() -> None:
    """Close the per-loop ``httpx.AsyncClient`` for the **currently running**
    event loop, if one was created.  Safe to call from a secondary loop
    (e.g. the one created by ``execute_source_run_locally``).

    Does nothing when the current loop is the main loop (the singleton
    is closed separately by ``close_async_client()`` during shutdown).
    """
    current_loop_id = id(asyncio.get_running_loop())
    if current_loop_id == _async_client_loop_id:
        return  # Singleton — closed by close_async_client()
    client = _secondary_clients.pop(current_loop_id, None)
    if client is not None:
        try:
            await client.aclose()
        except Exception:
            pass


async def close_async_client() -> None:
    """Close and release the global async HTTPX client, if created.

    Also closes any remaining per-loop clients.  Called during FastAPI
    lifespan shutdown.
    """
    global _async_client, _async_client_loop_id
    # Close the singleton.
    if _async_client is not None:
        await _async_client.aclose()
        _async_client = None
        _async_client_loop_id = None
    # Close any remaining per-loop clients.
    clients = list(_secondary_clients.values())
    _secondary_clients.clear()
    for client in clients:
        try:
            await client.aclose()
        except Exception:
            pass
