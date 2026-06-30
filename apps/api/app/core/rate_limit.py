"""In-process sliding-window rate limiter.

This is the in-memory rate limiter that backs PR2's
``POST /api/v1/auth/forgot-password`` endpoint: 5 requests per email per
hour, 6th gets 429. The design intentionally keeps state in the API
process — the API runs as a single Render Free web service, so an
in-process counter is correct and zero-latency.

The interface is intentionally narrow (constructor + ``.check``) so a
future Redis-backed implementation can be dropped in without changing
the call site. The Redis sketch lives in the design doc.

Thread safety: ``check`` is called concurrently from uvicorn workers and
the in-process scheduler. A ``threading.Lock`` covers the
prune-then-check-then-record critical section, so the maximum-requests
post-condition holds even under racing callers.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class SlidingWindowLimiter:
    """Per-key sliding-window rate limiter.

    Parameters
    ----------
    max_requests:
        Maximum number of requests allowed per key inside the window.
    window_seconds:
        Width of the sliding window, in seconds.
    max_keys:
        Soft cap on the number of distinct keys tracked. When the number
        of keys exceeds this, the oldest-touched key is evicted. The cap
        prevents an attacker from exhausting memory by spraying unique
        keys at the limiter. Default ``10_000`` — enough for a year of
        "5 req/hour/email" traffic for several thousand active users.

    Notes
    -----
    The limiter uses ``time.monotonic()`` for timestamps. ``monotonic`` is
    immune to wall-clock adjustments (NTP slew, leap seconds) which
    would otherwise cause spurious window-expired events.
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        max_keys: int = 10_000,
    ) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be >= 1")
        if window_seconds < 1:
            raise ValueError("window_seconds must be >= 1")
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._max_keys = max_keys
        # Per-key deque of monotonic timestamps inside the window. The
        # deque is ordered oldest-first; ``popleft`` evicts the oldest
        # timestamp when it ages out of the window.
        self._buckets: dict[str, deque[float]] = {}
        # Track touch order so we can LRU-evict the oldest key when
        # ``_buckets`` grows past ``_max_keys``. We re-key on every
        # check; the dict insertion order is the LRU order.
        self._lock = threading.Lock()

    def check(self, key: str) -> bool:
        """Record a hit on ``key`` and return whether it was allowed.

        Returns ``True`` if the hit is inside the budget, ``False`` if
        the key is currently rate-limited. A rejected hit is NOT recorded
        (a 429 doesn't extend the window — otherwise a sustained
        attacker keeps pushing the unlock time out forever).
        """
        with self._lock:
            now = time.monotonic()
            cutoff = now - self._window_seconds
            # Re-key to make this the most-recently-touched key. This
            # preserves the dict's insertion-order LRU invariant: the
            # oldest key is always ``next(iter(_buckets))``.
            bucket = self._buckets.pop(key, None)
            if bucket is None:
                bucket = deque()
            # Prune timestamps that have aged out of the window. We do
            # this BEFORE the budget check so a slow caller whose
            # earlier hits are now stale does not get a false 429.
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self._max_requests:
                # Reject — put the bucket back at the front of the LRU
                # order so the throttled key does not get evicted on the
                # next call from a different (newer) key.
                self._buckets[key] = bucket
                # Enforce the soft cap: if we're over, evict the oldest.
                self._evict_oldest_if_needed()
                return False
            # Accept: record the hit and reinsert the bucket.
            bucket.append(now)
            self._buckets[key] = bucket
            self._evict_oldest_if_needed()
            return True

    def _evict_oldest_if_needed(self) -> None:
        """Drop the oldest-touched key when the cap is exceeded.

        Caller must hold ``_lock``. Uses the dict's insertion-order
        invariant: the first key returned by ``__iter__`` is the
        least-recently-touched one (because we re-key on every check).
        """
        while len(self._buckets) > self._max_keys:
            oldest_key = next(iter(self._buckets))
            del self._buckets[oldest_key]
