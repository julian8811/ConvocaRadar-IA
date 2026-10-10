"""Persist acotada: ascun-convocatorias y novo-nordisk-grants mueren a ~90s
(scraping_max_source_seconds) en fase persist — cientos de candidatos con
HEAD url-check + embedding serial (~2s c/u) desbordan el presupuesto.

Cotas (runner + factory, sin tocar services/):
- paginacion WP acotada por fuente (ascun -> max_pages 3, como novo),
- warmup concurrente de url-checks (misma funcion + mismo TTL, solo antes),
- tope de items por run + timebox con reserva: en vez de TimeoutError ->
  failed con 0 items, el run completa con lo alcanzado y deja skip visible.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock


os.environ.setdefault("DATABASE_URL", "sqlite:///./test_convocaradar.db")

from app.schemas import OpportunityCreate  # noqa: E402


def _items(n: int) -> list[OpportunityCreate]:
    return [
        OpportunityCreate(
            title=f"Capped item {i}",
            entity="Test Entity",
            country="Colombia",
            official_url=f"https://example.com/capped/{i}",
            summary=f"Summary {i}",
        )
        for i in range(n)
    ]


def _ns_run() -> SimpleNamespace:
    return SimpleNamespace(logs=[])


def _created_result(data: OpportunityCreate) -> SimpleNamespace:
    now = datetime.now(UTC).replace(tzinfo=None)
    return SimpleNamespace(
        id=f"id-{data.title}",
        first_seen_at=now,
        last_seen_at=now,
        official_url=data.official_url,
    )


def _skip_log(run: SimpleNamespace) -> dict | None:
    for entry in run.logs:
        if isinstance(entry, dict) and entry.get("message") == "persist capped":
            return entry
    return None


async def test_persist_timebox_completes_instead_of_timeout(monkeypatch):
    """RED: con deadline corto, el loop para y completa (no TimeoutError)."""
    from app.scraper import runner

    async def _slow_create(db, data, organization_id=None):  # noqa: ANN001, ANN202
        await asyncio.sleep(0.05)
        return _created_result(data)

    monkeypatch.setattr(runner, "create_opportunity", _slow_create)
    monkeypatch.setattr(runner, "_warm_url_cache", AsyncMock())

    run = _ns_run()
    deadline = time.monotonic() + 0.15
    created, updated, failed = await runner._persist_opportunities(
        MagicMock(), run, _items(20), None, deadline=deadline
    )

    processed = created + updated
    assert processed >= 1, "timebox must persist at least one item"
    assert processed < 20, "timebox must stop before exhausting 20 slow items"
    assert failed == 0
    entry = _skip_log(run)
    assert entry is not None, "skip must stay visible in run.logs"
    assert entry["reason"] == "time_budget"
    assert entry["items_skipped"] == 20 - processed


async def test_persist_count_cap_truncates_with_visible_skip(monkeypatch):
    """RED: tope de items por run con skip observable."""
    from app.scraper import runner

    async def _fast_create(db, data, organization_id=None):  # noqa: ANN001, ANN202
        return _created_result(data)

    monkeypatch.setattr(runner, "create_opportunity", _fast_create)
    monkeypatch.setattr(runner, "_warm_url_cache", AsyncMock())
    monkeypatch.setattr(runner, "PERSIST_MAX_ITEMS_PER_RUN", 3)

    run = _ns_run()
    created, updated, failed = await runner._persist_opportunities(
        MagicMock(), run, _items(8), None
    )

    assert created + updated == 3
    assert failed == 0
    entry = _skip_log(run)
    assert entry is not None
    assert entry["reason"] == "count_cap"
    assert entry["items_skipped"] == 5


async def test_persist_under_caps_processes_everything(monkeypatch):
    """Triangulation: bajo las cotas, el path normal persiste todo sin skips."""
    from app.scraper import runner

    async def _fast_create(db, data, organization_id=None):  # noqa: ANN001, ANN202
        return _created_result(data)

    monkeypatch.setattr(runner, "create_opportunity", _fast_create)
    monkeypatch.setattr(runner, "_warm_url_cache", AsyncMock())

    run = _ns_run()
    created, updated, failed = await runner._persist_opportunities(
        MagicMock(), run, _items(5), None
    )

    assert (created, updated, failed) == (5, 0, 0)
    assert _skip_log(run) is None


async def test_url_warmup_checks_each_distinct_url_once(monkeypatch):
    """El warmup usa la misma validacion cacheada, una vez por URL distinta."""
    import app.services.validation as validation
    from app.scraper import runner

    calls: list[str] = []

    async def _fake_reachable(url: str) -> bool:
        calls.append(url)
        return True

    monkeypatch.setattr(validation, "async_url_is_reachable", _fake_reachable)

    urls = [
        "https://example.com/a",
        "https://example.com/a",
        "https://example.com/b",
        None,
    ]
    await runner._warm_url_cache(urls)

    assert sorted(calls) == ["https://example.com/a", "https://example.com/b"]


async def test_url_warmup_swallows_errors(monkeypatch):
    """El warmup es best-effort: si falla, el loop serial igual verifica."""
    import app.services.validation as validation
    from app.scraper import runner

    async def _boom(url: str) -> bool:
        raise RuntimeError("network down")

    monkeypatch.setattr(validation, "async_url_is_reachable", _boom)

    # Must not raise.
    await runner._warm_url_cache(["https://example.com/a"])


def test_ascun_wordpress_max_pages_capped():
    """RED: ascun-convocatorias (WP, ~9 paginas x100) va acotada como novo."""
    from app.connectors.factory import connector_for

    connector = connector_for(
        "ascun-convocatorias", "https://ascun.org.co/wp-json/wp/v2/posts", "html"
    )
    assert connector.__class__.__name__ == "WordPressGrantsConnector"
    assert connector.max_pages == 3, f"ascun fetch sin acotar: max_pages={connector.max_pages}"
