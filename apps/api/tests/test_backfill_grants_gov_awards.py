"""E9: grants-gov awards backfill script.

Covers scripts/backfill_grants_gov_awards.py with a mocked XHR layer and an
in-memory SQLite session:

- dry-run writes nothing (but still reports what would change),
- gap-fill never overwrites existing funding/dates,
- --limit is respected,
- a per-row XHR failure degrades to skipped, never aborts the batch.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "backfill_grants_gov_awards.py"
)


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "backfill_grants_gov_awards", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None, SCRIPT_PATH
    module = importlib.util.module_from_spec(spec)
    sys.modules["backfill_grants_gov_awards"] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()

_DETAIL_PAYLOAD = {
    "oppId": "351234",
    "oppTitle": "Rural Innovation Grant",
    "awardCeiling": "750000",
    "awardCeilingFormatted": "$750,000",
}


@pytest.fixture
def db() -> Session:
    from app.db.session import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _make_source(db: Session, key: str = "grants-gov"):
    from app.models import Source

    src = Source(
        name="Grants Gov",
        key=key,
        base_url="https://www.grants.gov/search-grants",
    )
    db.add(src)
    db.commit()
    return src


_OPP_SEQ = 0


def _make_opp(db: Session, source, **overrides):
    from app.models import Opportunity

    global _OPP_SEQ
    _OPP_SEQ += 1
    base = {
        "title": f"Test Grant {_OPP_SEQ}",
        "slug": f"test-grant-{_OPP_SEQ}",
        "entity": "USDA",
        "country": "United States",
        "official_url": f"https://www.grants.gov/search-results-detail/{351234 + _OPP_SEQ}",
        "summary": "summary",
        "raw_text": "raw",
        "external_id": str(351234 + _OPP_SEQ),
        "source_id": source.id,
    }
    base.update(overrides)
    opp = Opportunity(**base)
    db.add(opp)
    db.commit()
    return opp


def _mock_detail(monkeypatch, payload: dict | None = None, *, side_effect=None):
    if side_effect is not None:
        mock_fetch = AsyncMock(side_effect=side_effect)
    else:
        mock_fetch = AsyncMock(
            return_value=dict(payload if payload is not None else _DETAIL_PAYLOAD)
        )
    monkeypatch.setattr(
        "app.connectors.grants_gov._fetch_grants_gov_detail", mock_fetch
    )
    return mock_fetch


class TestDryRun:
    async def test_dry_run_writes_nothing_but_reports(self, db, monkeypatch):
        """Dry-run must not mutate the DB, yet reports the would-be fills."""
        src = _make_source(db)
        opp = _make_opp(db, src)
        _mock_detail(monkeypatch)
        sleep_fn = AsyncMock()

        summary = await script.run_backfill(
            db, limit=25, sleep_seconds=1.0, dry_run=True, sleep_fn=sleep_fn
        )

        db.refresh(opp)
        assert opp.funding_amount_value is None
        assert opp.funding_amount_raw is None
        assert summary["attempted"] == 1
        assert summary["filled"] == 1
        assert summary["skipped"] == 0


class TestGapFill:
    async def test_never_overwrites_existing_funding(self, db, monkeypatch):
        """Funded/raw-only rows are not selected; unfunded rows fill."""
        src = _make_source(db)
        funded = _make_opp(
            db,
            src,
            funding_amount_raw="USD 10,000",
            funding_amount_value=10000.0,
            funding_amount_currency="USD",
        )
        raw_only = _make_opp(
            db, src, funding_amount_raw="USD 10,000", funding_amount_value=None
        )
        unfunded = _make_opp(db, src)
        mock_fetch = _mock_detail(monkeypatch)
        sleep_fn = AsyncMock()

        summary = await script.run_backfill(
            db, limit=25, sleep_seconds=1.0, dry_run=False, sleep_fn=sleep_fn
        )

        db.refresh(funded)
        assert funded.funding_amount_value == 10000.0
        assert funded.funding_amount_raw == "USD 10,000"
        db.refresh(raw_only)
        assert raw_only.funding_amount_raw == "USD 10,000"
        assert raw_only.funding_amount_value is None
        db.refresh(unfunded)
        assert unfunded.funding_amount_value == 750000.0
        # Only the fully-unfunded row qualifies; funded/raw-only rows are
        # skipped by the shared XHR path, so no fetch is wasted on them.
        assert summary["attempted"] == 1
        assert summary["filled"] == 1
        assert mock_fetch.await_count == 1

    def test_apply_gap_fill_never_overwrites(self, db):
        """Unit: conflicting award fields leave existing funding/dates alone."""
        from datetime import datetime

        src = _make_source(db)
        opp = _make_opp(
            db,
            src,
            funding_amount_raw="USD 10,000",
            funding_amount_value=10000.0,
            funding_amount_currency="USD",
            open_date=datetime(2026, 1, 5),
            close_date=datetime(2026, 10, 31),
        )
        changed = script.apply_award_gap_fill(
            opp,
            {
                "funding_amount_raw": "$750,000",
                "funding_amount_value": 750000.0,
                "funding_amount_currency": "USD",
                "open_date": datetime(2026, 1, 1),
                "close_date": datetime(2026, 12, 31),
            },
        )
        assert changed is False
        assert opp.funding_amount_value == 10000.0
        assert opp.funding_amount_raw == "USD 10,000"
        assert opp.close_date == datetime(2026, 10, 31)
        assert opp.open_date == datetime(2026, 1, 5)


class TestLimit:
    async def test_limit_respected(self, db, monkeypatch):
        """Only --limit rows are attempted, however many qualify."""
        src = _make_source(db)
        for _ in range(5):
            _make_opp(db, src)
        mock_fetch = _mock_detail(monkeypatch)
        sleep_fn = AsyncMock()

        summary = await script.run_backfill(
            db, limit=2, sleep_seconds=1.0, dry_run=True, sleep_fn=sleep_fn
        )

        assert summary["attempted"] == 2
        assert summary["filled"] == 2
        assert mock_fetch.await_count == 2


class TestPerRowFailure:
    async def test_failure_degrades_per_row(self, db, monkeypatch):
        """One dead XHR degrades to skipped; the rest of the batch still fills."""
        src = _make_source(db)
        opps = [_make_opp(db, src) for _ in range(3)]
        failing_id = opps[1].external_id

        async def _flaky(opp_id: str):
            if opp_id == failing_id:
                raise RuntimeError("XHR down")
            return dict(_DETAIL_PAYLOAD)

        _mock_detail(monkeypatch, side_effect=_flaky)
        sleep_fn = AsyncMock()

        summary = await script.run_backfill(
            db, limit=25, sleep_seconds=1.0, dry_run=False, sleep_fn=sleep_fn
        )

        assert summary["attempted"] == 3
        assert summary["filled"] == 2
        assert summary["skipped"] == 1
        db.refresh(opps[0])
        db.refresh(opps[1])
        db.refresh(opps[2])
        assert opps[0].funding_amount_value == 750000.0
        assert opps[1].funding_amount_value is None
        assert opps[2].funding_amount_value == 750000.0


class TestBatching:
    async def test_politeness_sleep_and_commit_per_batch(self, db, monkeypatch):
        """3 rows with batch_size=2 → 1 sleep between batches, 2 commits."""
        src = _make_source(db)
        for _ in range(3):
            _make_opp(db, src)
        _mock_detail(monkeypatch)
        sleep_fn = AsyncMock()
        commits = []
        orig_commit = db.commit
        db.commit = lambda: (commits.append(1), orig_commit())  # noqa: E731

        try:
            summary = await script.run_backfill(
                db,
                limit=25,
                sleep_seconds=1.0,
                dry_run=False,
                batch_size=2,
                sleep_fn=sleep_fn,
            )
        finally:
            db.commit = orig_commit

        assert summary["attempted"] == 3
        assert summary["filled"] == 3
        sleep_fn.assert_awaited_once_with(1.0)
        assert len(commits) == 2
