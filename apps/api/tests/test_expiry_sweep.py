"""T3 (vigencia S4): sweeper diario purga vencidas con backup rotativo.

S4: backup verificado antes de borrar (si el backup falla, aborta sin
tocar filas); solo `close_date` pasada (nunca unknown sin fecha);
dependientes primero (precedente purge-trio); retención rotativa.
Corre dentro del loop del scheduler junto al nightly (hook en main.py).

RED: falla mientras app.services.expiry no exista.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import Base
from app.models import Opportunity, Source


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _source(db: Session, key: str = "t3-src") -> Source:
    src = Source(name=key, key=key, base_url="https://example.com/x")
    db.add(src)
    db.commit()
    return src


_OPP_SEQ = 0


def _opp(db: Session, src: Source, title: str, close_date) -> Opportunity:
    global _OPP_SEQ
    _OPP_SEQ += 1
    opp = Opportunity(
        title=title,
        slug=f"t3-{_OPP_SEQ}",
        entity="E",
        country="C",
        official_url="https://example.com/x",
        summary="s",
        description="d",
        external_id=f"t3-{_OPP_SEQ}",
        source_id=src.id,
        close_date=close_date,
    )
    db.add(opp)
    db.commit()
    return opp


def _puts(monkeypatch) -> tuple[list, list]:
    puts: list = []
    deletes: list = []

    def _put(key: str, content: bytes, content_type: str):
        from app.core.storage import StoredObject

        puts.append((key, content_type))
        return StoredObject(storage_path=f"s3://bucket/{key}", backend="s3")

    def _delete(storage_path: str) -> None:
        deletes.append(storage_path)

    monkeypatch.setattr("app.services.expiry.storage_put_bytes", _put)
    monkeypatch.setattr("app.services.expiry.storage_delete_object", _delete)
    return puts, deletes


class TestExpirySweep:
    def test_purges_only_past_close_with_backup(self, db, monkeypatch):
        from app.services.expiry import purge_expired_opportunities

        src = _source(db)
        _opp(db, src, "Vencida", _now() - timedelta(days=10))
        _opp(db, src, "Vigente", _now() + timedelta(days=30))
        _opp(db, src, "Sin fecha", None)
        puts, _ = _puts(monkeypatch)

        result = purge_expired_opportunities(db, today=date(2026, 10, 18))

        assert result["expired_found"] == 1
        assert result["deleted"] == 1
        assert result["aborted_reason"] is None
        assert len(puts) == 1
        assert puts[0][0] == "expiry-sweeps/2026-10-18.json"
        remaining = sorted(o.title for o in db.query(Opportunity).all())
        assert remaining == ["Sin fecha", "Vigente"]

    def test_no_expired_writes_no_backup(self, db, monkeypatch):
        from app.services.expiry import purge_expired_opportunities

        src = _source(db)
        _opp(db, src, "Vigente", _now() + timedelta(days=5))
        puts, deletes = _puts(monkeypatch)

        result = purge_expired_opportunities(db, today=date(2026, 10, 18))

        assert result["expired_found"] == 0
        assert result["deleted"] == 0
        assert puts == [] and deletes == []

    def test_backup_failure_aborts_without_deleting(self, db, monkeypatch):
        from app.services.expiry import purge_expired_opportunities

        src = _source(db)
        _opp(db, src, "Vencida", _now() - timedelta(days=3))

        def _boom(key: str, content: bytes, content_type: str):
            raise RuntimeError("minio caído")

        monkeypatch.setattr("app.services.expiry.storage_put_bytes", _boom)
        result = purge_expired_opportunities(db, today=date(2026, 10, 18))

        assert result["deleted"] == 0
        assert result["aborted_reason"] is not None
        assert db.query(Opportunity).count() == 1

    def test_prunes_backups_beyond_retention(self, db, monkeypatch):
        from app.services.expiry import purge_expired_opportunities

        src = _source(db)
        _opp(db, src, "Vencida", _now() - timedelta(days=1))
        _, deletes = _puts(monkeypatch)

        purge_expired_opportunities(db, today=date(2026, 10, 18), backup_retain=7)

        assert "expiry-sweeps/2026-10-10.json" in deletes
        assert not any("2026-10-1" in d and d > "expiry-sweeps/2026-10-10.json" for d in deletes if "2026-10-1" in d)
        assert "expiry-sweeps/2026-10-18.json" not in deletes


class TestExpiryWiring:
    def test_settings_defaults(self):
        from app.core.config import Settings

        fields = Settings.model_fields
        assert fields["expiry_sweep_enabled"].default is True
        assert fields["expiry_sweep_hour"].default == 2
        assert fields["expiry_backup_retain_days"].default == 7

    def test_scheduler_loop_calls_sweeper(self):
        import inspect

        import app.main as main_module

        source = inspect.getsource(main_module._run_periodic_source_sweep)
        assert "purge_expired_opportunities" in source
        assert "expiry_sweep_enabled" in source
