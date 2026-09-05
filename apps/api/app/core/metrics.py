"""Metrics for faculty matching (T9)."""
from __future__ import annotations

import time
from collections import Counter

_counters: Counter = Counter()
_scores: list[float] = []
_llm_hits = 0
_llm_total = 0
_p1_latency: list[float] = []


def record_match(final_score: float, llm_hit: bool) -> None:
    _counters["matching_count"] += 1
    _scores.append(final_score)
    _llm_total += 1
    if llm_hit:
        _llm_hits += 1
    else:
        _counters["llm_fallback"] += 1


def record_p1_latency(ms: float) -> None:
    _p1_latency.append(ms)


def get_metrics() -> dict:
    avg = sum(_scores) / len(_scores) if _scores else 0.0
    fallback_rate = (_counters["llm_fallback"] / _llm_total) if _llm_total else 0.0
    # p95 for latency if needed
    return {
        "matching_count": _counters["matching_count"],
        "avg_final_score": round(avg, 4),
        "llm_fallback_rate": round(fallback_rate, 4),
        "llm_hits": _llm_hits,
        "llm_total": _llm_total,
    }


def reset_metrics() -> None:
    _counters.clear()
    _scores.clear()
    global _llm_hits, _llm_total
    _llm_hits = 0
    _llm_total = 0
    _p1_latency.clear()
