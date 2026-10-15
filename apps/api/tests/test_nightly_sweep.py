"""Nightly forced sweep trigger: pure decision helper, no DB."""

from __future__ import annotations

import datetime as _dt


def _cot(hour: int, minute: int = 0, day: int = 15) -> _dt.datetime:
    return _dt.datetime(2026, 10, day, hour, minute,
                        tzinfo=_dt.timezone(_dt.timedelta(hours=-5)))


def test_fires_first_tick_after_1am():
    from app.services.connectors import _nightly_force_due

    assert _nightly_force_due(_cot(1, 0), hour=1, enabled=True, last_forced_date=None) is True
    assert _nightly_force_due(_cot(1, 29), hour=1, enabled=True, last_forced_date=None) is True


def test_silent_before_1am():
    from app.services.connectors import _nightly_force_due

    assert _nightly_force_due(_cot(0, 59), hour=1, enabled=True, last_forced_date=None) is False


def test_once_per_day():
    from app.services.connectors import _nightly_force_due
    from datetime import date

    today = date(2026, 10, 15)
    assert _nightly_force_due(_cot(1, 30), hour=1, enabled=True, last_forced_date=today) is False
    assert _nightly_force_due(_cot(1, 5, day=16), hour=1, enabled=True,
                              last_forced_date=today) is True


def test_disabled_never_fires():
    from app.services.connectors import _nightly_force_due

    assert _nightly_force_due(_cot(3, 0), hour=1, enabled=False, last_forced_date=None) is False
