from datetime import datetime, timedelta
from types import SimpleNamespace

from app.services.connectors import source_due_for_scraping


NOW = datetime(2026, 9, 7, 12, 0, 0)


def _source(*, frequency: str, last_run_at, failures: int = 0):
    return SimpleNamespace(
        id="cadence-test-source",
        scraping_frequency=frequency,
        last_run_at=last_run_at,
        consecutive_empty_runs=failures,
    )


def test_never_run_source_is_due() -> None:
    source = _source(frequency="daily", last_run_at=None)
    assert source_due_for_scraping(source, now=NOW) is True


def test_hourly_source_is_not_due_before_one_hour() -> None:
    source = _source(frequency="hourly", last_run_at=NOW - timedelta(minutes=59))
    assert source_due_for_scraping(source, now=NOW) is False


def test_hourly_source_is_due_after_cadence_plus_max_jitter() -> None:
    source = _source(frequency="hourly", last_run_at=NOW - timedelta(minutes=71))
    assert source_due_for_scraping(source, now=NOW) is True


def test_daily_source_is_not_due_before_one_day() -> None:
    source = _source(frequency="daily", last_run_at=NOW - timedelta(hours=23, minutes=59))
    assert source_due_for_scraping(source, now=NOW) is False


def test_daily_source_is_due_after_cadence_plus_max_jitter() -> None:
    source = _source(frequency="daily", last_run_at=NOW - timedelta(hours=24, minutes=11))
    assert source_due_for_scraping(source, now=NOW) is True


def test_heavily_failing_daily_source_gets_extra_backoff() -> None:
    source = _source(
        frequency="daily",
        last_run_at=NOW - timedelta(hours=30),
        failures=5,
    )
    assert source_due_for_scraping(source, now=NOW) is False


def test_unknown_frequency_defaults_to_daily_cadence() -> None:
    source = _source(frequency="custom", last_run_at=NOW - timedelta(hours=12))
    assert source_due_for_scraping(source, now=NOW) is False
