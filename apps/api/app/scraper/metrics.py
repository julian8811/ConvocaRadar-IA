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
# ── Per-source extraction completeness (022 P2) ──────────────────────────────
_counter_funding_parsed_total: int = 0
_counter_close_extracted_total: int = 0
_counter_open_extracted_total: int = 0
_gauge_funding_coverage: dict[str, float] = {}  # source_key -> 0-100 %
_gauge_close_coverage: dict[str, float] = {}  # source_key -> 0-100 %
_gauge_open_coverage: dict[str, float] = {}  # source_key -> 0-100 %
_per_source_extraction: dict[str, dict[str, int]] = {}  # source -> {total, funding, close, open}
# ── 023 gauges (throttle/burst) ───────────────────────────────────────────
_counter_throttled: int = 0
_gauge_burst_utilization: dict[str, float] = {}
_gauge_delay_for_wait: float = 0.0


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


def record_extraction(
    *,
    source_key: str,
    funding_present: bool,
    close_present: bool,
    open_present: bool = False,
) -> None:
    """Per-source completeness counters for funding/close/open (022 P2)."""
    with _lock:
        global _counter_funding_parsed_total, _counter_close_extracted_total, _counter_open_extracted_total
        if funding_present:
            _counter_funding_parsed_total += 1
        if close_present:
            _counter_close_extracted_total += 1
        if open_present:
            _counter_open_extracted_total += 1
        entry = _per_source_extraction.setdefault(
            source_key, {"total": 0, "funding": 0, "close": 0, "open": 0}
        )
        entry["total"] += 1
        if funding_present:
            entry["funding"] += 1
        if close_present:
            entry["close"] += 1
        if open_present:
            entry["open"] += 1
        total = entry["total"]
        _gauge_funding_coverage[source_key] = round(entry["funding"] / total * 100, 1) if total else 0
        _gauge_close_coverage[source_key] = round(entry["close"] / total * 100, 1) if total else 0
        _gauge_open_coverage[source_key] = round(entry["open"] / total * 100, 1) if total else 0


def record_throttled(*, source_key: str = "unknown", delay_s: float = 0.0) -> None:
    with _lock:
        global _counter_throttled, _gauge_delay_for_wait
        _counter_throttled += 1
        _gauge_delay_for_wait = round(float(delay_s), 3)
        if source_key:
            _gauge_burst_utilization[source_key] = round(min(_counter_throttled / 150 * 100, 100), 1)


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
            "funding_parsed_total": _counter_funding_parsed_total,
            "close_extracted_total": _counter_close_extracted_total,
            "open_extracted_total": _counter_open_extracted_total,
            "funding_coverage": dict(_gauge_funding_coverage),
            "close_coverage": dict(_gauge_close_coverage),
            "open_coverage": dict(_gauge_open_coverage),
            "per_source_extraction": {k: dict(v) for k, v in _per_source_extraction.items()},
            "throttled_count": _counter_throttled,
            "burst_utilization": dict(_gauge_burst_utilization),
            "delay_for_wait": _gauge_delay_for_wait,
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
        global _counter_funding_parsed_total, _counter_close_extracted_total, _counter_open_extracted_total
        _counter_items_found = 0
        _counter_scrapes = 0
        _counter_errors = 0
        _counter_funding_parsed_total = 0
        _counter_close_extracted_total = 0
        _counter_open_extracted_total = 0
        _gauge_health.clear()
        _gauge_funding_coverage.clear()
        _gauge_close_coverage.clear()
        _gauge_open_coverage.clear()
        _per_source_extraction.clear()
        global _counter_throttled, _gauge_delay_for_wait
        _counter_throttled = 0
        _gauge_delay_for_wait = 0.0
        _gauge_burst_utilization.clear()
