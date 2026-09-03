"""Priority queue for source sweep — tier + domain budget aware.

Ordering: strategic (tier=1) > complementary (2) > experimental (3) > untiered.
Within same tier, earlier due / more stale first. Dedup by source id,
defers if domain budget exhausted.
"""
from __future__ import annotations

import time
from collections import deque

TIER_ORDER = {"strategic": 0, "complementary": 1, "experimental": 2, None: 3, "": 3}


def tier_rank(tier: str | None) -> int:
    return TIER_ORDER.get(tier, 3)


class PriorityQueue:
    """Simple tier-priority queue for Source objects."""

    def __init__(self) -> None:
        self._items: list = []
        self._seen: set[str] = set()
        self._deferred: deque = deque()

    def enqueue(self, source) -> bool:
        sid = getattr(source, "id", None) or getattr(source, "key", None)
        if sid in self._seen:
            return False
        self._seen.add(sid)
        self._items.append(source)
        return True

    def drain_ordered(self) -> list:
        """Return items sorted by tier, with deferred re-queued at tail.

        Filters throttled domains via DomainBudgetManager.delay_for().
        """
        # sort by tier then by last_success staleness (None first)
        def _key(s):
            return (tier_rank(getattr(s, "tier", None)), getattr(s, "last_success_at", None) is not None)

        ordered = sorted(self._items, key=_key)
        self._items.clear()

        # respect domain rate limit: defer throttled to next cycle
        try:
            from app.scraper.domain_budget import get_domain_budget

            budget = get_domain_budget()
            ready: list = []
            for src in ordered:
                url = getattr(src, "base_url", "") or ""
                if url and budget.delay_for(url) > 0:
                    self._deferred.append(src)
                else:
                    ready.append(src)
            # re-queue deferred for next drain
            if self._deferred:
                # keep deferred for next sweep without losing them
                self._items.extend(list(self._deferred))
                self._deferred.clear()
            return ready
        except Exception:
            return ordered

    def __len__(self) -> int:
        return len(self._items)

    def clear(self) -> None:
        self._items.clear()
        self._seen.clear()
        self._deferred.clear()


def build_priority_queue(sources: list) -> PriorityQueue:
    q = PriorityQueue()
    for s in sources:
        q.enqueue(s)
    return q
