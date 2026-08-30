"""Dedicated Playwright browser pool — isolates Playwright lifecycle per connector.

Wraps DomainBudgetManager's playwright slot as a context manager that
acquires/release the global slot and surfaces isolation so a crash in
connector A never affects connector B (fresh browser per acquire).
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from app.core.config import get_settings
from app.scraper.domain_budget import get_domain_budget


class PlaywrightBrowserPool:
    """One-slot-per-acquire pool for Playwright browsers (023 S3: slot=1 only for SPA retry)."""

    def __init__(self) -> None:
        self._budget = get_domain_budget()

    async def acquire(self, url: str, timeout_s: float | None = None) -> None:
        settings = get_settings()
        deadline = asyncio.get_running_loop().time() + (timeout_s or min(30.0, max(5.0, float(settings.scraping_timeout_seconds))))
        acquired = self._budget.acquire("playwright")
        while not acquired and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.1)
            acquired = self._budget.acquire("playwright")
        if not acquired:
            raise RuntimeError(f"Playwright pool saturated for {url} — max {self._budget._max_concurrent_for('playwright')}")

    def release(self, url: str = "playwright") -> None:
        self._budget.release(url)

    @asynccontextmanager
    async def slot(self, url: str) -> AsyncIterator[None]:
        await self.acquire(url)
        try:
            yield
        finally:
            self.release(url)


_pool: PlaywrightBrowserPool | None = None


def get_playwright_pool() -> PlaywrightBrowserPool:
    global _pool
    if _pool is None:
        _pool = PlaywrightBrowserPool()
    return _pool
