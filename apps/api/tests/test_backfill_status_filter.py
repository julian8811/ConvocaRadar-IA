"""--status filter for the LLM backfill: only actionable rows get LLM spend."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from app.db.session import Base


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _opp(db: Session, slug: str, status: str, **kw) -> None:
    from app.models import Opportunity

    base = {
        "title": "T %s" % slug, "slug": slug, "entity": "E", "country": "C",
        "status": status,
    }
    base.update(kw)
    db.add(Opportunity(**base))
    db.commit()


def test_status_filter_selects_only_open_thin(db: Session) -> None:
    from backfill_llm_extraction import fetch_targets

    _opp(db, "open-thin", "open")
    _opp(db, "unknown-thin", "unknown")
    _opp(db, "open-full", "open", close_date=__import__("datetime").datetime(2026, 12, 1),
         funding_amount_value=10.0, open_date=__import__("datetime").datetime(2026, 1, 1))
    got = fetch_targets(db, None, 10, ["open"])
    assert [o.slug for o in got] == ["open-thin"]


def test_no_filter_keeps_old_behavior(db: Session) -> None:
    from backfill_llm_extraction import fetch_targets

    _opp(db, "open-thin", "open")
    _opp(db, "unknown-thin", "unknown")
    got = fetch_targets(db, None, 10, None)
    assert sorted(o.slug for o in got) == ["open-thin", "unknown-thin"]
