"""E16: systematic LLM backfill script.

Covers scripts/backfill_llm_extraction.py with a mocked
``extract_opportunity_structured`` and an in-memory SQLite session:

- dry-run writes nothing (but still reports what would change),
- gap-fill never overwrites existing open/close/funding/summary,
- oldest-first ordering by updated_at ASC (the reanalyze-all flaw),
- --limit is respected,
- local-provider extractions only persist when they yield a missing field,
- a per-row extraction failure degrades to failed/skipped, never aborts.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "backfill_llm_extraction.py"
)


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "backfill_llm_extraction", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None, SCRIPT_PATH
    module = importlib.util.module_from_spec(spec)
    sys.modules["backfill_llm_extraction"] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()


def _extraction(data: dict, provider: str = "gemini"):
    from app.core.ai import AIExtraction

    return AIExtraction(data=data, confidence=0.9, provider=provider)


_FULL_DATA = {
    "close_date": "2026-12-31",
    "open_date": "2026-01-05",
    "funding_amount_raw": "USD 50,000",
    "funding_amount_value": 50000.0,
    "funding_amount_currency": "USD",
    "summary": "LLM summary",
}


@pytest.fixture
def db() -> Session:
    from app.db.session import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _make_source(db: Session, key: str = "test-source"):
    from app.models import Source

    src = Source(name="Test Source", key=key, base_url="https://example.com")
    db.add(src)
    db.commit()
    return src


_OPP_SEQ = 0


def _make_opp(db: Session, source, **overrides):
    from app.models import Opportunity

    global _OPP_SEQ
    _OPP_SEQ += 1
    base = {
        "title": f"Test Opp {_OPP_SEQ}",
        "slug": f"test-opp-{_OPP_SEQ}",
        "entity": "Test Entity",
        "country": "United States",
        "official_url": "https://example.com/opp",
        "summary": "",
        "description": "detailed description of the funding opportunity " * 10,
        "raw_text": "full raw text of the funding opportunity " * 10,
        "external_id": f"ext-{_OPP_SEQ}",
        "source_id": source.id,
    }
    base.update(overrides)
    opp = Opportunity(**base)
    db.add(opp)
    db.commit()
    return opp


def _mock_extraction(monkeypatch, data: dict | None = None, *, provider="gemini", side_effect=None):
    if side_effect is not None:
        mock = AsyncMock(side_effect=side_effect)
    else:
        mock = AsyncMock(return_value=_extraction(dict(data if data is not None else _FULL_DATA), provider))
    monkeypatch.setattr("app.core.ai.extract_opportunity_structured", mock)
    return mock


class TestDryRun:
    async def test_dry_run_writes_nothing_but_reports(self, db, monkeypatch):
        """Dry-run must not mutate the DB, yet reports the would-be fills."""
        src = _make_source(db)
        opp = _make_opp(db, src)
        _mock_extraction(monkeypatch)
        sleep_fn = AsyncMock()

        summary = await script.run_backfill(
            db, limit=100, sleep_seconds=1.0, dry_run=True, sleep_fn=sleep_fn
        )

        db.refresh(opp)
        assert opp.close_date is None
        assert opp.open_date is None
        assert opp.funding_amount_value is None
        assert summary["scanned"] == 1
        assert summary["filled"] == 1
        assert summary["skipped"] == 0
        assert summary["failed"] == 0


class TestGapFill:
    async def test_never_overwrites_existing_fields(self, db, monkeypatch):
        """Complete rows are not selected; conflicting LLM data never overwrites."""
        src = _make_source(db)
        complete = _make_opp(
            db,
            src,
            open_date=datetime(2026, 1, 5),
            close_date=datetime(2026, 10, 31),
            funding_amount_raw="USD 10,000",
            funding_amount_value=10000.0,
            funding_amount_currency="USD",
            summary="Existing substantive summary",
        )
        missing = _make_opp(db, src)
        _mock_extraction(monkeypatch)
        sleep_fn = AsyncMock()

        summary = await script.run_backfill(
            db, limit=100, sleep_seconds=1.0, dry_run=False, sleep_fn=sleep_fn
        )

        db.refresh(complete)
        assert complete.close_date == datetime(2026, 10, 31)
        assert complete.open_date == datetime(2026, 1, 5)
        assert complete.funding_amount_value == 10000.0
        assert complete.funding_amount_raw == "USD 10,000"
        assert complete.summary == "Existing substantive summary"
        db.refresh(missing)
        assert missing.close_date is not None
        assert missing.funding_amount_value == 50000.0
        # Only the incomplete row qualifies.
        assert summary["scanned"] == 1
        assert summary["filled"] == 1

    def test_gap_fill_unit_never_overwrites(self):
        """Unit: conflicting parsed fields leave existing values alone."""
        updates = script.llm_gap_fill_updates(
            existing_open=datetime(2026, 1, 5),
            existing_close=datetime(2026, 10, 31),
            existing_raw="USD 10,000",
            existing_value=10000.0,
            existing_currency="USD",
            existing_summary="Existing summary",
            fields={
                "open_date": datetime(2026, 2, 1),
                "close_date": datetime(2026, 12, 31),
                "funding_amount_raw": "USD 50,000",
                "funding_amount_value": 50000.0,
                "funding_amount_currency": "USD",
                "summary": "LLM summary",
            },
        )
        assert updates == {}


class TestOldestFirst:
    async def test_oldest_first_ordering(self, db, monkeypatch):
        """Targets are processed oldest-first so repeated runs progress."""
        src = _make_source(db)
        now = datetime(2026, 1, 1)
        # Create newest first to prove selection reorders.
        new = _make_opp(db, src, title="new", updated_at=now + timedelta(days=2))
        mid = _make_opp(db, src, title="mid", updated_at=now + timedelta(days=1))
        old = _make_opp(db, src, title="old", updated_at=now)
        calls: list[str] = []

        async def _recording(text: str):
            calls.append(text)
            return _extraction(dict(_FULL_DATA))

        monkeypatch.setattr(
            "app.core.ai.extract_opportunity_structured", AsyncMock(side_effect=_recording)
        )
        sleep_fn = AsyncMock()

        await script.run_backfill(
            db, limit=100, sleep_seconds=1.0, dry_run=True, sleep_fn=sleep_fn
        )

        assert len(calls) == 3
        assert "old" in calls[0]
        assert "mid" in calls[1]
        assert "new" in calls[2]


class TestLimit:
    async def test_limit_respected(self, db, monkeypatch):
        """Only --limit rows are attempted, however many qualify."""
        src = _make_source(db)
        for _ in range(5):
            _make_opp(db, src)
        mock = _mock_extraction(monkeypatch)
        sleep_fn = AsyncMock()

        summary = await script.run_backfill(
            db, limit=2, sleep_seconds=1.0, dry_run=True, sleep_fn=sleep_fn
        )

        assert summary["scanned"] == 2
        assert mock.await_count == 2


class TestSourceKey:
    async def test_source_key_scopes_selection(self, db, monkeypatch):
        """--source-key restricts to one source; default covers all."""
        src_a = _make_source(db, key="source-a")
        src_b = _make_source(db, key="source-b")
        _make_opp(db, src_a)
        _make_opp(db, src_b)
        _mock_extraction(monkeypatch)
        sleep_fn = AsyncMock()

        scoped = await script.run_backfill(
            db, limit=100, sleep_seconds=1.0, dry_run=True,
            source_key="source-a", sleep_fn=sleep_fn,
        )
        assert scoped["scanned"] == 1

        unscoped = await script.run_backfill(
            db, limit=100, sleep_seconds=1.0, dry_run=True, sleep_fn=sleep_fn
        )
        assert unscoped["scanned"] == 2


class TestLocalProvider:
    async def test_local_with_nothing_new_skips_without_write(self, db, monkeypatch):
        """Local extraction yielding no missing field → skipped, no write."""
        src = _make_source(db)
        opp = _make_opp(
            db, src,
            open_date=datetime(2026, 1, 5),
            close_date=datetime(2026, 10, 31),
            summary="Existing summary",
        )
        # Row lacks only funding; local yields no funding-like raw.
        _mock_extraction(
            monkeypatch, {"summary": "local words " * 20}, provider="local"
        )
        sleep_fn = AsyncMock()

        summary = await script.run_backfill(
            db, limit=100, sleep_seconds=1.0, dry_run=False, sleep_fn=sleep_fn
        )

        db.refresh(opp)
        assert opp.funding_amount_value is None
        assert opp.summary == "Existing summary"
        assert summary["scanned"] == 1
        assert summary["filled"] == 0
        assert summary["skipped"] == 1

    async def test_local_with_missing_date_still_fills(self, db, monkeypatch):
        """Local regex dates on full text CAN fill a row missing dates."""
        src = _make_source(db)
        opp = _make_opp(
            db, src,
            funding_amount_raw="USD 10,000",
            funding_amount_value=10000.0,
            funding_amount_currency="USD",
        )
        _mock_extraction(
            monkeypatch, {"close_date": "2026-12-31"}, provider="local"
        )
        sleep_fn = AsyncMock()

        summary = await script.run_backfill(
            db, limit=100, sleep_seconds=1.0, dry_run=False, sleep_fn=sleep_fn
        )

        db.refresh(opp)
        assert opp.close_date is not None
        assert summary["filled"] == 1


class TestPerRowFailure:
    async def test_failure_isolated(self, db, monkeypatch):
        """One dead extraction degrades to failed; the batch still fills."""
        src = _make_source(db)
        opps = [_make_opp(db, src) for _ in range(3)]

        async def _flaky(text: str):
            if opps[1].title in text:
                raise RuntimeError("LLM down")
            return _extraction(dict(_FULL_DATA))

        monkeypatch.setattr(
            "app.core.ai.extract_opportunity_structured", AsyncMock(side_effect=_flaky)
        )
        sleep_fn = AsyncMock()

        summary = await script.run_backfill(
            db, limit=100, sleep_seconds=1.0, dry_run=False, sleep_fn=sleep_fn
        )

        assert summary["scanned"] == 3
        assert summary["filled"] == 2
        assert summary["failed"] == 1
        assert summary["skipped"] == 0
        db.refresh(opps[0])
        db.refresh(opps[1])
        db.refresh(opps[2])
        assert opps[0].close_date is not None
        assert opps[1].close_date is None
        assert opps[2].close_date is not None


class TestBatching:
    async def test_politeness_sleep_and_commit_per_batch(self, db, monkeypatch):
        """3 rows with batch_size=2 → 1 sleep between batches, 2 commits."""
        src = _make_source(db)
        for _ in range(3):
            _make_opp(db, src)
        _mock_extraction(monkeypatch)
        sleep_fn = AsyncMock()
        commits = []
        orig_commit = db.commit
        db.commit = lambda: (commits.append(1), orig_commit())  # noqa: E731

        try:
            summary = await script.run_backfill(
                db,
                limit=100,
                sleep_seconds=1.0,
                dry_run=False,
                batch_size=2,
                sleep_fn=sleep_fn,
            )
        finally:
            db.commit = orig_commit

        assert summary["scanned"] == 3
        assert summary["filled"] == 3
        sleep_fn.assert_awaited_once_with(1.0)
        assert len(commits) == 2


class TestMinTextLength:
    async def test_short_text_skipped_without_llm_call(self, db, monkeypatch):
        """Rows below --min-text-length never reach the LLM (dry-run)."""
        src = _make_source(db)
        _make_opp(db, src, title="Hi", description="short", raw_text="tiny")
        mock = _mock_extraction(monkeypatch)
        sleep_fn = AsyncMock()

        summary = await script.run_backfill(
            db, limit=100, sleep_seconds=0, dry_run=True, sleep_fn=sleep_fn
        )

        assert mock.await_count == 0
        assert summary["scanned"] == 1
        assert summary["filled"] == 0
        assert summary["skipped"] == 1
        assert summary["short_text_skipped"] == 1

    async def test_short_text_skipped_in_real_mode_no_write(self, db, monkeypatch):
        """Short rows are skipped without writes even when persisting."""
        src = _make_source(db)
        opp = _make_opp(db, src, title="Hi", description="short", raw_text="tiny")
        mock = _mock_extraction(monkeypatch)
        sleep_fn = AsyncMock()

        summary = await script.run_backfill(
            db, limit=100, sleep_seconds=0, dry_run=False, sleep_fn=sleep_fn
        )

        db.refresh(opp)
        assert mock.await_count == 0
        assert opp.close_date is None
        assert summary["skipped"] == 1
        assert summary["short_text_skipped"] == 1

    async def test_long_text_still_calls_llm(self, db, monkeypatch):
        """Rows at/above the threshold still go through extraction."""
        src = _make_source(db)
        _make_opp(db, src, title="Rich opportunity", description="x" * 250, raw_text="")
        mock = _mock_extraction(monkeypatch)
        sleep_fn = AsyncMock()

        summary = await script.run_backfill(
            db, limit=100, sleep_seconds=0, dry_run=True, sleep_fn=sleep_fn
        )

        assert mock.await_count == 1
        assert summary["filled"] == 1
        assert summary["short_text_skipped"] == 0

    async def test_custom_threshold_respected(self, db, monkeypatch):
        """An explicit min_text_length overrides the default 200."""
        src = _make_source(db)
        _make_opp(db, src, title="Hi", description="short", raw_text="tiny")
        mock = _mock_extraction(monkeypatch)
        sleep_fn = AsyncMock()

        summary = await script.run_backfill(
            db, limit=100, sleep_seconds=0, dry_run=True,
            sleep_fn=sleep_fn, min_text_length=5,
        )

        assert mock.await_count == 1
        assert summary["short_text_skipped"] == 0

    def test_default_min_text_length_is_200(self):
        """Default threshold is 200 chars (argparse + run_backfill agree)."""
        import argparse as _ap
        assert script.DEFAULT_MIN_TEXT_LENGTH == 200
        import inspect as _inspect
        assert _inspect.signature(script.run_backfill).parameters[
            "min_text_length"
        ].default == 200
