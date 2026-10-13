"""--null-only mode for scripts/backfill_sector.py.

Zero network: stub ``classify_fn`` + in-memory SQLite session.

- flag filters to NULL/empty sectors only (low-conf and high-conf ignored),
- ordering stays updated_at ASC among NULLs,
- dry-run writes nothing,
- --limit is respected,
- compat pin: without the flag the current gap-fill behavior is unchanged.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "backfill_sector.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("backfill_sector_nullonly", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None, SCRIPT_PATH
    module = importlib.util.module_from_spec(spec)
    sys.modules["backfill_sector_nullonly"] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()


@pytest.fixture
def db():
    from app.db.session import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


_SEQ = 0


def _make_opp(db, **overrides):
    from app.models import Opportunity

    global _SEQ
    _SEQ += 1
    base = {
        "title": f"NullOnly Opp {_SEQ}",
        "slug": f"nullonly-opp-{_SEQ}",
        "entity": "Test Entity",
        "country": "Colombia",
        "description": "Convocatoria de turismo sostenible",
    }
    base.update(overrides)
    opp = Opportunity(**base)
    db.add(opp)
    db.commit()
    return opp


def _stub_classifier(sector="turismo", confidence=0.9, source="rules"):
    calls: list[str] = []

    def classify(text: str) -> tuple[str, float, str]:
        calls.append(text)
        return (sector, confidence, source)

    classify.calls = calls  # type: ignore[attr-defined]
    return classify


class TestNullOnlyFilter:
    async def test_only_null_sectors_qualify(self, db):
        """Mixed NULL/low-conf/high-conf/confidence-less → only NULLs scanned."""
        null_opp = _make_opp(db, title="null row")
        _make_opp(db, title="low conf row", sector="turismo",
                  sector_confidence=0.5, sector_source="rules")
        _make_opp(db, title="high conf row", sector="turismo",
                  sector_confidence=0.95, sector_source="rules")
        _make_opp(db, title="no confidence row", sector="turismo",
                  sector_confidence=None, sector_source="rules")
        classify = _stub_classifier()
        summary = await script.run_backfill(
            db, limit=100, sleep_seconds=0, dry_run=True,
            null_only=True, classify_fn=classify,
        )
        assert summary["scanned"] == 1
        assert len(classify.calls) == 1
        assert "null row" in classify.calls[0]
        db.refresh(null_opp)
        assert null_opp.sector is None  # dry-run writes nothing

    async def test_empty_string_sector_also_qualifies(self, db):
        empty_opp = _make_opp(db, title="empty row", sector="")
        classify = _stub_classifier()
        summary = await script.run_backfill(
            db, limit=100, sleep_seconds=0, dry_run=True,
            null_only=True, classify_fn=classify,
        )
        assert summary["scanned"] == 1
        assert "empty row" in classify.calls[0]
        db.refresh(empty_opp)
        assert empty_opp.sector == ""

    def test_needs_sector_null_only_predicate(self):
        from app.models import Opportunity

        assert script.needs_sector(Opportunity(sector=None), null_only=True) is True
        assert script.needs_sector(Opportunity(sector=""), null_only=True) is True
        assert script.needs_sector(Opportunity(sector="turismo"), null_only=True) is False
        low = Opportunity(sector="turismo", sector_confidence=0.5)
        assert script.needs_sector(low, null_only=True) is False
        high = Opportunity(sector="turismo", sector_confidence=0.95)
        assert script.needs_sector(high, null_only=True) is False


class TestNullOnlyOrdering:
    async def test_null_rows_processed_oldest_first(self, db):
        base = datetime(2026, 1, 1)
        # Newest NULL created first to prove selection reorders.
        _make_opp(db, title="null new", updated_at=base + timedelta(days=2))
        _make_opp(db, title="null mid", updated_at=base + timedelta(days=1))
        _make_opp(db, title="null old", updated_at=base)
        # Low-conf row older than every NULL: must NOT jump the queue.
        old_low = _make_opp(
            db, title="low conf oldest", sector="otros",
            sector_confidence=0.3, sector_source="rules",
            updated_at=base - timedelta(days=30),
        )
        classify = _stub_classifier()
        summary = await script.run_backfill(
            db, limit=100, sleep_seconds=0, dry_run=True,
            null_only=True, classify_fn=classify,
        )
        assert summary["scanned"] == 3
        assert len(classify.calls) == 3
        assert "null old" in classify.calls[0]
        assert "null mid" in classify.calls[1]
        assert "null new" in classify.calls[2]
        db.refresh(old_low)
        assert old_low.sector == "otros"


class TestNullOnlyLimit:
    async def test_limit_respected(self, db):
        for _ in range(3):
            _make_opp(db)
        classify = _stub_classifier()
        summary = await script.run_backfill(
            db, limit=2, sleep_seconds=0, dry_run=True,
            null_only=True, classify_fn=classify,
        )
        assert summary["scanned"] == 2
        assert len(classify.calls) == 2


class TestNullOnlyDryRun:
    async def test_dry_run_writes_nothing(self, db):
        opp = _make_opp(db)
        classify = _stub_classifier("salud", 0.85, "llm")
        summary = await script.run_backfill(
            db, limit=10, sleep_seconds=0, dry_run=True,
            null_only=True, classify_fn=classify,
        )
        db.refresh(opp)
        assert opp.sector is None
        assert summary["filled"] == 1
        assert summary["dry_run"] is True

    async def test_real_run_persists(self, db):
        opp = _make_opp(db)
        classify = _stub_classifier("salud", 0.85, "llm")
        summary = await script.run_backfill(
            db, limit=10, sleep_seconds=0, dry_run=False,
            null_only=True, classify_fn=classify,
        )
        db.refresh(opp)
        assert (opp.sector, opp.sector_confidence, opp.sector_source) == (
            "salud", 0.85, "llm",
        )
        assert summary["filled"] == 1


class TestDefaultBehaviorUnchanged:
    async def test_low_confidence_still_qualifies_without_flag(self, db):
        """Compat pin: no flag → current gap-fill contract (low-conf in)."""
        low = _make_opp(db, title="low conf row", sector="turismo",
                        sector_confidence=0.5, sector_source="rules")
        classify = _stub_classifier("salud", 0.85, "llm")
        summary = await script.run_backfill(
            db, limit=10, sleep_seconds=0, dry_run=False,
            classify_fn=classify,
        )
        db.refresh(low)
        assert low.sector == "salud"
        assert summary["scanned"] == 1
