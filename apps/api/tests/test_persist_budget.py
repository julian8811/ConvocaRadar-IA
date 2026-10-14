"""Per-item persist budget: one slow candidate must not blow the run budget.

Context: ascun-convocatorias / cost-open-calls hit ~90s TimeoutError in the
post-parse phase even after the count-cap + loop timebox landed
(see test_persist_bounds.py). Root hole: the timebox deadline is only
consulted *between* items, so a single slow ``create_opportunity`` (serial
LLM enrich with ``llm_timeout_seconds=45`` + 2x HEAD url-check at 5s each +
gateway embedding) blocks past the deadline and the outer
``wait_for(remaining)`` in ``run_source_inline`` raises TimeoutError ->
failed run with 0 items.

Contract under test (``app/scraper/runner.py::_persist_opportunities``):
- with a deadline, one item may never consume more than the remaining
  persist budget; the slow item is recorded as failed and the loop keeps
  going / stops with a visible ``persist capped`` skip;
- without a deadline, historical unbounded behavior is preserved.
Zero network: ``create_opportunity`` and ``_warm_url_cache`` are stubbed.
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
            title=f"Budget item {i}",
            entity="Test Entity",
            country="Colombia",
            official_url=f"https://example.com/budget/{i}",
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


async def test_persist_slow_item_cannot_exceed_remaining_budget(monkeypatch):
    """RED: [fast, slow(8s), fast] with a ~1s deadline must return in <<8s."""
    from app.scraper import runner

    async def _mixed_create(db, data, organization_id=None):  # noqa: ANN001, ANN202
        if data.title == "Budget item 1":
            await asyncio.sleep(8.0)  # stands in for LLM 45s + HEADs + embedding
        return _created_result(data)

    monkeypatch.setattr(runner, "create_opportunity", _mixed_create)
    monkeypatch.setattr(runner, "_warm_url_cache", AsyncMock())

    run = _ns_run()
    deadline = time.monotonic() + 1.0
    started = time.monotonic()
    created, updated, failed = await runner._persist_opportunities(
        MagicMock(), run, _items(3), None, deadline=deadline
    )
    wall = time.monotonic() - started

    assert wall < 5.0, f"one slow item blocked the loop for {wall:.1f}s"
    assert created == 1, "first fast item must persist"
    assert failed == 1, "slow item must be recorded as failed, not hang the run"


async def test_persist_no_deadline_keeps_unbounded_behavior(monkeypatch):
    """Triangulation: deadline=None preserves the historical unbounded path."""
    from app.scraper import runner

    async def _slow_create(db, data, organization_id=None):  # noqa: ANN001, ANN202
        await asyncio.sleep(0.2)
        return _created_result(data)

    monkeypatch.setattr(runner, "create_opportunity", _slow_create)
    monkeypatch.setattr(runner, "_warm_url_cache", AsyncMock())

    run = _ns_run()
    created, updated, failed = await runner._persist_opportunities(
        MagicMock(), run, _items(2), None
    )

    assert (created, updated, failed) == (2, 0, 0)
