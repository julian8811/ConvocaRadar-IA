"""Regression tests for conservative past-due status reconciliation."""
from datetime import datetime
from unittest import TestCase
from unittest.mock import patch
from zoneinfo import ZoneInfo
import sys
from types import ModuleType

from sqlalchemy import DateTime, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_script_path = Path(__file__).resolve().parents[3] / "scripts" / "reconcile_expired_status.py"
_script_spec = spec_from_file_location("reconcile_expired_status", _script_path)
_script = module_from_spec(_script_spec)
_script_spec.loader.exec_module(_script)
reconcile = _script.reconcile
cutoff_for_previous_dates = _script.cutoff_for_previous_dates


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String)


class Opportunity(Base):
    __tablename__ = "opportunities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"))
    status: Mapped[str] = mapped_column(String)
    close_date: Mapped[datetime | None] = mapped_column(DateTime)


class TestConservativeReconciliation(TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add(Source(id=1, key="sample"))
        for id_, status, day in [
            (1, "open", datetime(2026, 10, 10, 14)),
            (2, "closing_soon", datetime(2026, 10, 11, 22)),
            (3, "open", datetime(2026, 10, 12, 0)),
            (4, "open", datetime(2026, 10, 13, 18)),
            (5, "unknown", datetime(2026, 10, 9)),
            (6, "closed", datetime(2026, 10, 9)),
            (7, "open", None),
        ]:
            self.db.add(Opportunity(id=id_, source_id=1, status=status, close_date=day))
        self.db.commit()
        app_models = ModuleType("app.models")
        app_models.Opportunity, app_models.Source = Opportunity, Source
        self.patch_modules = patch.dict(sys.modules, {"app.models": app_models})
        self.patch_modules.start()
        self.now = datetime(2026, 10, 12, 8, 40, tzinfo=ZoneInfo("America/Bogota"))

    def tearDown(self):
        self.patch_modules.stop()
        self.db.close()
        self.engine.dispose()

    def test_preview_does_not_modify_records(self):
        result = reconcile(self.db, apply=False, now=self.now)
        self.assertEqual(2, result["candidates"])
        self.assertFalse(result["applied"])
        self.assertEqual("open", self.db.get(Opportunity, 1).status)

    def test_apply_only_before_today_and_idempotent(self):
        result = reconcile(self.db, apply=True, expected_count=2, now=self.now)
        self.assertEqual(2, result["updated"])
        self.assertEqual("closed", self.db.get(Opportunity, 1).status)
        self.assertEqual("closed", self.db.get(Opportunity, 2).status)
        self.assertEqual("open", self.db.get(Opportunity, 3).status)
        self.assertEqual("unknown", self.db.get(Opportunity, 5).status)
        self.assertEqual(0, reconcile(self.db, apply=False, now=self.now)["candidates"])

    def test_mismatched_count_aborts(self):
        with self.assertRaisesRegex(ValueError, "expected 3, observed 2"):
            reconcile(self.db, apply=True, expected_count=3, now=self.now)
        self.assertEqual("open", self.db.get(Opportunity, 1).status)

    def test_change_cap_aborts(self):
        with self.assertRaisesRegex(ValueError, "exceeds"):
            reconcile(self.db, apply=True, expected_count=2, max_changes=1, now=self.now)
        self.assertEqual("open", self.db.get(Opportunity, 1).status)

    def test_bogota_date_cutoff(self):
        self.assertEqual(datetime(2026, 10, 12), cutoff_for_previous_dates(self.now))
