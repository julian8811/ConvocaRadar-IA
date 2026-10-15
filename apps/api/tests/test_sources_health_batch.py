"""Batched source-health parity: one GROUP BY must match per-source math.

Performance: get_sources_health() cost ~2.35s on prod (207 sources x N+1
runs query + 4 coverage queries each). The batched path must return
field-identical results.
"""

from __future__ import annotations

import datetime as _dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base


@pytest.fixture
def health_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _seed_health_data(health_db):
    from app.models import Opportunity, Organization, Source, SourceRun

    org = Organization(slug="perf-org", name="Perf Org", type="university", country="Colombia")
    health_db.add(org)
    health_db.commit()

    full = Source(
        organization_id=org.id, name="Full", key="perf-full",
        base_url="https://example.com/full", scraping_frequency="daily",
    )
    empty = Source(
        organization_id=org.id, name="Empty", key="perf-empty",
        base_url="https://example.com/empty", scraping_frequency="weekly",
    )
    health_db.add_all([full, empty])
    health_db.commit()

    now = _dt.datetime.now().replace(microsecond=0)
    health_db.add(
        SourceRun(
            source_id=full.id, status="success", items_found=4,
            items_created=3, items_updated=1,
            started_at=now - _dt.timedelta(hours=2), finished_at=now - _dt.timedelta(hours=1),
        )
    )
    opps = [
        Opportunity(
            organization_id=org.id, source_id=full.id, title="Call %d" % i,
            slug="perf-call-%d" % i, entity="E", country="Colombia",
            close_date=now + _dt.timedelta(days=30) if i < 2 else None,
            funding_amount_value=1000.0 if i < 1 else None,
            official_url="https://example.com/%d" % i if i < 3 else None,
        )
        for i in range(4)
    ]
    health_db.add_all(opps)
    health_db.commit()
    return org, full, empty


def test_coverage_ratios_many_matches_per_source(health_db):
    from app.api.v1.sources import _source_coverage_ratios, _source_coverage_ratios_many

    org, full, empty = _seed_health_data(health_db)
    batched = _source_coverage_ratios_many(health_db, [full.id, empty.id])
    assert batched[full.id] == _source_coverage_ratios(health_db, full.id)
    assert batched[empty.id] == (0.0, 0.0, 0.0)
    assert batched[full.id] == (50.0, 25.0, 75.0)


def test_get_sources_health_matches_per_source_loop(health_db):
    from app.api.v1.sources import _source_health
    from app.services.dashboard import get_sources_health

    org, full, empty = _seed_health_data(health_db)
    batched = {h.key: h for h in get_sources_health(health_db, org.id)}
    assert set(batched) == {"perf-full", "perf-empty"}
    for source in (full, empty):
        expected = _source_health(health_db, source)
        got = batched[source.key]
        assert got.model_dump() == expected.model_dump()
