"""Tests for Change C — Health Score & Quality Gate.

Covers:
- calculate_source_health_score formula (pure function)
- health_status_for_score mapping
- tier classification behavior
- auto-pause after consecutive empty runs
- dispatcher skips auto_paused sources
- SourceHealthRead includes health_score/health_status/tier/auto_paused
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_source_health_score.db")
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("STORAGE_DIR", "./test_storage_health_score")
os.environ.setdefault("SMTP_HOST", "")
os.environ.setdefault("JWT_SECRET", "a" * 64)
os.environ.setdefault("INTERNAL_API_KEY", "a" * 64)
os.environ.setdefault("BOOTSTRAP_SOURCES_ON_STARTUP", "false")

from pathlib import Path

Path("test_source_health_score.db").unlink(missing_ok=True)

import pytest  # noqa: E402

# ── Health score formula (pure function tests) ─────────────────────────────


def test_calculate_source_health_score_perfect_inputs() -> None:
    """All metrics at maximum should yield a score of 100."""
    from app.services.scoring import calculate_source_health_score

    score = calculate_source_health_score(
        success_rate=100.0,
        avg_items_found=100.0,
        close_date_coverage=100.0,
        amount_coverage=100.0,
        url_coverage=100.0,
        freshness_days=0,
        selector_stability=100.0,
    )
    assert score == 100


def test_calculate_source_health_score_minimum_inputs() -> None:
    """All metrics at minimum should yield a score of 0."""
    from app.services.scoring import calculate_source_health_score

    score = calculate_source_health_score(
        success_rate=0.0,
        avg_items_found=0.0,
        close_date_coverage=0.0,
        amount_coverage=0.0,
        url_coverage=0.0,
        freshness_days=None,
        selector_stability=0.0,
    )
    assert score == 0


def test_calculate_source_health_score_mid_range() -> None:
    """Halfway metrics should yield a score near 50."""
    from app.services.scoring import calculate_source_health_score

    score = calculate_source_health_score(
        success_rate=50.0,
        avg_items_found=5.0,
        close_date_coverage=50.0,
        amount_coverage=50.0,
        url_coverage=50.0,
        freshness_days=30,
        selector_stability=50.0,
    )
    # Each component weighted: success_rate (30%*50=15), avg_items (20%*25=5),
    # close_date (15%*50=7.5), amount (10%*50=5), url (10%*50=5),
    # freshness (10%*50=5), selector (5%*50=2.5) = 45
    assert 40 <= score <= 50


def test_calculate_source_health_score_weights_are_respected() -> None:
    """Success rate (30%) should dominate the score."""
    from app.services.scoring import calculate_source_health_score

    # High success rate, everything else low
    score_high_success = calculate_source_health_score(
        success_rate=100.0,
        avg_items_found=0.0,
        close_date_coverage=0.0,
        amount_coverage=0.0,
        url_coverage=0.0,
        freshness_days=None,
        selector_stability=0.0,
    )
    # 30% of 100 = 30
    assert score_high_success == 30

    # Low success rate, everything else high
    score_low_success = calculate_source_health_score(
        success_rate=0.0,
        avg_items_found=100.0,
        close_date_coverage=100.0,
        amount_coverage=100.0,
        url_coverage=100.0,
        freshness_days=0,
        selector_stability=100.0,
    )
    # 30% of 0 = 0, 20%*100=20, 15%*100=15, 10%*100=10, 10%*100=10, 10%*100=10, 5%*100=5
    # Total = 70
    assert score_low_success == 70


def test_calculate_source_health_score_freshness_decay() -> None:
    """Freshness should decay with days since last success."""
    from app.services.scoring import calculate_source_health_score

    # Recent success
    recent = calculate_source_health_score(
        success_rate=100.0, avg_items_found=10.0,
        close_date_coverage=100.0, amount_coverage=100.0,
        url_coverage=100.0, freshness_days=1, selector_stability=100.0,
    )
    # Very stale
    stale = calculate_source_health_score(
        success_rate=100.0, avg_items_found=10.0,
        close_date_coverage=100.0, amount_coverage=100.0,
        url_coverage=100.0, freshness_days=365, selector_stability=100.0,
    )
    assert recent > stale
    # The difference should be at least the weight of freshness (10% * 100 = 10)
    assert recent - stale >= 10


def test_calculate_source_health_score_avg_items_normalized() -> None:
    """avg_items_found should be normalized to 0-100 scale."""
    from app.services.scoring import calculate_source_health_score

    # Very high items found
    high = calculate_source_health_score(
        success_rate=0.0, avg_items_found=500.0,
        close_date_coverage=0.0, amount_coverage=0.0,
        url_coverage=0.0, freshness_days=None, selector_stability=0.0,
    )
    # Very low items found
    low = calculate_source_health_score(
        success_rate=0.0, avg_items_found=0.0,
        close_date_coverage=0.0, amount_coverage=0.0,
        url_coverage=0.0, freshness_days=None, selector_stability=0.0,
    )
    assert high >= low
    # With nothing else contributing, the max from avg_items is 20
    assert high <= 20
    assert low == 0


def test_calculate_source_health_score_clamps_to_100() -> None:
    """Score should never exceed 100 even with extreme inputs."""
    from app.services.scoring import calculate_source_health_score

    score = calculate_source_health_score(
        success_rate=100.0, avg_items_found=9999.0,
        close_date_coverage=100.0, amount_coverage=100.0,
        url_coverage=100.0, freshness_days=0, selector_stability=100.0,
    )
    assert score <= 100


def test_calculate_source_health_score_returns_int() -> None:
    """Score must be an integer."""
    from app.services.scoring import calculate_source_health_score

    score = calculate_source_health_score(
        success_rate=73.5, avg_items_found=4.2,
        close_date_coverage=60.0, amount_coverage=30.0,
        url_coverage=80.0, freshness_days=5, selector_stability=90.0,
    )
    assert isinstance(score, int)


def test_calculate_source_health_score_partial_coverage() -> None:
    """Partial coverage values should produce intermediate scores."""
    from app.services.scoring import calculate_source_health_score

    # Only success rate and avg_items contribute; everything else zero
    score = calculate_source_health_score(
        success_rate=80.0, avg_items_found=10.0,
        close_date_coverage=0.0, amount_coverage=0.0,
        url_coverage=0.0, freshness_days=None, selector_stability=0.0,
    )
    # 80*0.30 + 20*0.20 + 0 + 0 + 0 + 0 + 0 = 24 + 4 = 28
    assert score == 28


def test_calculate_source_health_score_selector_stability_contributes() -> None:
    """Selector stability (5%) should contribute proportionally."""
    from app.services.scoring import calculate_source_health_score

    base = calculate_source_health_score(
        success_rate=0.0, avg_items_found=0.0,
        close_date_coverage=0.0, amount_coverage=0.0,
        url_coverage=0.0, freshness_days=None, selector_stability=0.0,
    )
    with_stability = calculate_source_health_score(
        success_rate=0.0, avg_items_found=0.0,
        close_date_coverage=0.0, amount_coverage=0.0,
        url_coverage=0.0, freshness_days=None, selector_stability=100.0,
    )
    # 5% of 100 = 5 points contribution
    assert with_stability - base == 5


def test_calculate_source_health_score_all_mid_values() -> None:
    """All metrics at 50% should yield a score around 50."""
    from app.services.scoring import calculate_source_health_score

    score = calculate_source_health_score(
        success_rate=50.0, avg_items_found=25.0,  # 50 on normalized scale
        close_date_coverage=50.0, amount_coverage=50.0,
        url_coverage=50.0, freshness_days=3,  # 80 on freshness scale
        selector_stability=50.0,
    )
    # success_rate: 50*0.30 = 15
    # avg_items: 50*0.20 = 10
    # close_date: 50*0.15 = 7.5
    # amount: 50*0.10 = 5
    # url: 50*0.10 = 5
    # freshness: 80*0.10 = 8
    # selector: 50*0.05 = 2.5
    # Total: 15+10+7.5+5+5+8+2.5 = 53
    assert 50 <= score <= 56


# ── Health status mapping ─────────────────────────────────────────────────


def test_health_status_for_score_mapping() -> None:
    """Verify all health status thresholds."""
    from app.services.scoring import health_status_for_score

    assert health_status_for_score(100) == "healthy"
    assert health_status_for_score(90) == "healthy"
    assert health_status_for_score(89) == "stable"
    assert health_status_for_score(70) == "stable"
    assert health_status_for_score(69) == "degraded"
    assert health_status_for_score(50) == "degraded"
    assert health_status_for_score(49) == "critical"
    assert health_status_for_score(0) == "critical"


def test_health_status_for_score_boundaries() -> None:
    """Boundary values should map to the correct status."""
    from app.services.scoring import health_status_for_score

    assert health_status_for_score(90) == "healthy"
    assert health_status_for_score(89) == "stable"
    assert health_status_for_score(70) == "stable"
    assert health_status_for_score(69) == "degraded"
    assert health_status_for_score(50) == "degraded"
    assert health_status_for_score(49) == "critical"


# ── Auto-pause logic ──────────────────────────────────────────────────────


def test_consecutive_empty_runs_increments_on_zero_items() -> None:
    """After a scrape with 0 items, consecutive_empty_runs increments by 1."""
    from app.services.scoring import update_consecutive_empty_runs

    assert update_consecutive_empty_runs(items_found=0, current_count=0) == 1
    assert update_consecutive_empty_runs(items_found=0, current_count=2) == 3
    assert update_consecutive_empty_runs(items_found=0, current_count=5) == 6


def test_consecutive_empty_runs_resets_on_items_found() -> None:
    """After a scrape with items found, consecutive_empty_runs resets to 0."""
    from app.services.scoring import update_consecutive_empty_runs

    assert update_consecutive_empty_runs(items_found=1, current_count=3) == 0
    assert update_consecutive_empty_runs(items_found=10, current_count=0) == 0
    assert update_consecutive_empty_runs(items_found=100, current_count=5) == 0


def test_auto_pause_triggered_after_three_empty_runs() -> None:
    """After 3 consecutive empty runs, auto_paused should be True."""
    from app.services.scoring import should_auto_pause

    assert should_auto_pause(new_count=3) is True
    assert should_auto_pause(new_count=4) is True
    assert should_auto_pause(new_count=2) is False
    assert should_auto_pause(new_count=0) is False
    assert should_auto_pause(new_count=1) is False


# ── SourceHealthRead shape ─────────────────────────────────────────────────


def test_source_health_read_includes_new_fields() -> None:
    """SourceHealthRead must include health_score, health_status, tier, auto_paused."""
    from app.schemas import SourceHealthRead

    instance = SourceHealthRead(
        source_id="test-id",
        key="test-key",
        name="Test Source",
        source_type="html",
        status="healthy",
        recent_runs=0,
        recent_failures=0,
        recent_items_found=0,
        recent_items_created=0,
        recent_items_updated=0,
        health_score=85,
        health_status="stable",
        tier="strategic",
        auto_paused=False,
    )
    assert instance.health_score == 85
    assert instance.health_status == "stable"
    assert instance.tier == "strategic"
    assert instance.auto_paused is False


def test_source_health_read_new_fields_defaults() -> None:
    """New fields should have sensible defaults."""
    from app.schemas import SourceHealthRead

    instance = SourceHealthRead(
        source_id="test-id",
        key="test-key",
        name="Test Source",
        source_type="html",
        status="healthy",
        recent_runs=0,
        recent_failures=0,
        recent_items_found=0,
        recent_items_created=0,
        recent_items_updated=0,
    )
    assert instance.health_score == 0
    assert instance.health_status == "unknown"
    assert instance.tier is None
    assert instance.auto_paused is False


# ── Source model fields ────────────────────────────────────────────────────


def test_source_model_has_new_fields() -> None:
    """Source model must have tier, auto_paused, consecutive_empty_runs columns."""
    from app.models import Source

    # Check the columns exist via Mapped descriptors (SA 2.x style)
    assert hasattr(Source, "tier")
    assert hasattr(Source, "auto_paused")
    assert hasattr(Source, "consecutive_empty_runs")


# ── Dispatcher auto_paused guard ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_source_returns_none_when_source_auto_paused() -> None:
    """run_source should return None immediately when source.auto_paused is True."""
    from unittest.mock import AsyncMock, MagicMock
    from app.models import Source
    from app.scraper.dispatcher import run_source

    source = MagicMock(spec=Source)
    source.auto_paused = True
    source.id = "test-source-id"

    db = MagicMock()
    result = await run_source(db, source, organization_id="test-org")
    assert result is None
