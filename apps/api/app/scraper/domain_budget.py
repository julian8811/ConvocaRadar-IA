"""Per-domain token bucket rate limiter for the scraping pipeline.

Each domain gets a configurable number of concurrent slots and an optional
delay between requests. Thread-safe via ``threading.Lock``, following the
same concurrency pattern as ``app.core.rate_limit.SlidingWindowLimiter``.

Usage
-----
    budget = DomainBudgetManager()
    delay = budget.delay_for(url)
    if delay > 0:
        await asyncio.sleep(delay)
    if budget.acquire(url):
        try:
            # ... make HTTP request ...
        finally:
            budget.release(url)
"""

from __future__ import annotations

import fnmatch
import threading
import time
from urllib.parse import urlparse


class DomainBudgetManager:
    """Per-domain token bucket rate limiter.

    Manages concurrent request slots per domain with configurable limits
    and inter-request delays. Thread-safe.

    Parameters
    ----------
    defaults:
        Optional override for the default budget configuration dict.
        Keys are domain names or glob patterns; values are dicts with
        ``max_concurrent`` and ``delay_seconds``. If ``None``, uses the
        built-in ``DEFAULTS`` class attribute.

    Notes
    -----
    The manager uses ``time.monotonic()`` for timestamps, making it
    immune to wall-clock adjustments (NTP slew, leap seconds).

    Lookup order:
    1. Exact domain match in ``defaults``
    2. Glob pattern match against domain
    3. Fallback default (2 concurrent, no delay)
    """

    DEFAULTS: dict[str, dict[str, int]] = {
        "grants.gov": {"max_concurrent": 3, "delay_seconds": 0},
        "beta.grants.gov": {"max_concurrent": 3, "delay_seconds": 0},
        "minciencias.gov.co": {"max_concurrent": 1, "delay_seconds": 2},
        "innpulsacolombia.com": {"max_concurrent": 1, "delay_seconds": 1},
        "*playwright*": {"max_concurrent": 1, "delay_seconds": 0},
    }

    _FALLBACK: dict[str, int] = {"max_concurrent": 2, "delay_seconds": 0}

    def __init__(
        self,
        defaults: dict[str, dict[str, int]] | None = None,
    ) -> None:
        self._defaults = defaults if defaults is not None else dict(self.DEFAULTS)
        self._lock = threading.Lock()
        # Per-domain current concurrent request count
        self._slots: dict[str, int] = {}
        # Per-domain monotonic timestamp of the last acquired request
        self._last_times: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def acquire(self, url: str) -> bool:
        """Try to acquire a concurrent slot for the given URL's domain.

        Returns ``True`` if a slot was acquired (within the configured
        ``max_concurrent`` budget). Returns ``False`` if the domain is at
        capacity — the caller should back off and retry later.

        On success, records the acquisition time so that
        :meth:`delay_for` can calculate inter-request spacing.

        Thread-safe: acquires ``self._lock``.
        """
        domain = self._domain_from_url(url)
        max_concurrent = self._max_concurrent_for(domain)

        with self._lock:
            current = self._slots.get(domain, 0)
            if current >= max_concurrent:
                return False
            self._slots[domain] = current + 1
            self._last_times[domain] = time.monotonic()
            return True

    def release(self, url: str) -> None:
        """Release a previously acquired slot for the given URL's domain.

        Safe to call even if no slot was acquired for this domain — the
        call is a no-op when the count is already zero.

        Thread-safe: acquires ``self._lock``.
        """
        domain = self._domain_from_url(url)
        with self._lock:
            current = self._slots.get(domain, 0)
            if current > 0:
                self._slots[domain] = current - 1

    def delay_for(self, url: str) -> float:
        """Return the number of seconds to wait before the next request.

        Based on the configured ``delay_seconds`` for the URL's domain and
        the time elapsed since the last :meth:`acquire` call on that domain.

        Returns ``0.0`` if no delay is configured, if no prior request was
        made to this domain, or if the delay window has elapsed.

        Thread-safe: reads ``self._last_times`` under ``self._lock``.
        """
        domain = self._domain_from_url(url)
        config = self._config_for(domain)
        delay_seconds = config.get("delay_seconds", 0)

        if delay_seconds <= 0:
            return 0.0

        with self._lock:
            last = self._last_times.get(domain, 0.0)

        elapsed = time.monotonic() - last
        if elapsed < delay_seconds:
            return delay_seconds - elapsed
        return 0.0

    def clear(self) -> None:
        """Reset all budgets and timestamps — return to initial state.

        Thread-safe: acquires ``self._lock``. Intended for test teardown
        and administrative reset.
        """
        with self._lock:
            self._slots.clear()
            self._last_times.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _domain_from_url(url: str) -> str:
        """Extract the lowercase hostname from *url*, stripping any port."""
        parsed = urlparse(url)
        hostname = parsed.hostname or parsed.netloc or ""
        # Strip port suffix if present
        if ":" in hostname:
            hostname = hostname.split(":")[0]
        return hostname.lower()

    def _config_for(self, domain: str) -> dict[str, int]:
        """Look up the budget config dict for *domain*.

        Resolution order:
        1. Exact match in ``self._defaults``
        2. Glob pattern match in ``self._defaults``
        3. Built-in fallback (2 concurrent, no delay)
        """
        domain_lower = domain.lower()

        # 1. Exact match
        if domain_lower in self._defaults:
            return dict(self._defaults[domain_lower])

        # 2. Glob pattern match — iterate patterns and check fnmatch
        for pattern, config in self._defaults.items():
            if fnmatch.fnmatch(domain_lower, pattern):
                return dict(config)

        # 3. Fallback
        return dict(self._FALLBACK)

    def _max_concurrent_for(self, domain: str) -> int:
        """Return the max concurrent slots for *domain*."""
        return self._config_for(domain).get("max_concurrent", 2)


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------

_domain_budget: DomainBudgetManager | None = None


def get_domain_budget() -> DomainBudgetManager:
    """Return the module-level DomainBudgetManager singleton.

    Lazily initialized on first call. Thread-safe after init (the
    singleton reference itself is set once). Use this from the
    connector layer to avoid passing the budget through every
    fetch function's argument list.
    """
    global _domain_budget
    if _domain_budget is None:
        _domain_budget = DomainBudgetManager()
    return _domain_budget
