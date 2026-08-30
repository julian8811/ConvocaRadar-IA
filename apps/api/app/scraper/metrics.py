"""Scraper observability — in-process metrics for /metrics endpoint.

Provides histogram buckets for scrape_duration, counters for items_found,
and gauges for health_score. All in-memory, queried by main.py:/metrics
and emitted via structlog per-source spans.
"""
from __future__ import annotations

import threading
import structlog

_struct = structlog.get_logger(__name__)

_lock = threading.Lock()
_histogram: list[float] = []  # scrape_duration seconds
_counter_items_found: int = 0
_counter_scrapes: int = 0
_counter_errors: int = 0
_gauge_health: dict[str, int] = {}  # source_key -> health_score


def record_scrape(*, source_key: str, duration_s: float, items_found: int, status: str, health_score: int | None = None) -> None:
    with _lock:
        _histogram.append(duration_s)
        # cap to 1000 samples to bound memory
        if len(_histogram) > 1000:
            _histogram[:] = _histogram[-1000:]
        global _counter_items_found, _counter_scrapes, _counter_errors
        _counter_scrapes += 1
        _counter_items_found += max(0, items_found)
        if status in ("failed", "degraded"):
            _counter_errors += 1
        if health_score is not None:
            _gauge_health[source_key] = health_score
    _struct.info(
        "scrape_metrics",
        source_key=source_key,
        duration_s=round(duration_s, 3),
        items_found=items_found,
        status=status,
        health_score=health_score,
    )


def snapshot() -> dict:
    with _lock:
        hist = list(_histogram)
        return {
            "scrape_duration_count": len(hist),
            "scrape_duration_p50": _percentile(hist, 50) if hist else 0,
            "scrape_duration_p95": _percentile(hist, 95) if hist else 0,
            "scrape_duration_avg": round(sum(hist) / len(hist), 3) if hist else 0,
            "items_found_total": _counter_items_found,
            "scrapes_total": _counter_scrapes,
            "errors_total": _counter_errors,
            "health_gauges": dict(_gauge_health),
        }


def _percentile(data: list[float], p: int) -> float:
    if not data:
        return 0
    s = sorted(data)
    k = (len(s) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return round(float(s[f]), 3)
    d = k - f
    return round(float(s[f] * (1 - d) + s[c] * d), 3)


def reset() -> None:
    with _lock:
        _histogram.clear()
        global _counter_items_found, _counter_scrapes, _counter_errors
        _counter_items_found = 0
        _counter_scrapes = 0
        _counter_errors = 0
        _gauge_health.clear()
