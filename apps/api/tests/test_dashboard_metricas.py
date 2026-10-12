"""R1 metric fixes: DISTINCT KPIs, unique scores, consistent coverage scope.

TDD RED tests for odd/tasks/panel-reestructurado.md Problem 1/2/6.

Duplicate-row cleanup procedure (deploy, server-side, out of test scope):
  1. Verify duplicates BEFORE migrating (exact verification SQL):
       SELECT opportunity_id, organization_id, COUNT(*)
       FROM opportunity_scores
       GROUP BY opportunity_id, organization_id
       HAVING COUNT(*) > 1;
  2. Keep the newest row per (opportunity_id, organization_id), delete rest:
       DELETE FROM opportunity_scores a USING opportunity_scores b
       WHERE a.id < b.id
         AND a.opportunity_id = b.opportunity_id
         AND a.organization_id = b.organization_id;
     (SQLite variant for local verification:
       DELETE FROM opportunity_scores
       WHERE id NOT IN (
         SELECT MAX(id) FROM opportunity_scores
         GROUP BY opportunity_id, organization_id
       );)
  3. Re-run the verification query — must return zero rows.
  4. Then apply migration 0018 (creates the unique constraint).
The migration itself never deletes data; it only adds the constraint.

Verification:
  cd apps/api && python -m pytest tests/test_dashboard_metricas.py -q
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import UniqueConstraint, create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import Base
from app.models import Opportunity, OpportunityEmbedding, OpportunityScore, Source, SourceRun
from app.services import dashboard as dashboard_svc


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def legacy_db() -> Session:
    """In-memory DB with the PRE-0018 schema: no unique constraint on scores.

    Simulates production rows before the server-side duplicate cleanup ran,
    so KPI tests prove DISTINCT works even with legacy duplicate rows.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[t for t in Base.metadata.sorted_tables if t.name != "opportunity_scores"],
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE opportunity_scores ("
                "id VARCHAR NOT NULL PRIMARY KEY, "
                "opportunity_id VARCHAR NOT NULL, "
                "organization_id VARCHAR NOT NULL, "
                "score FLOAT NOT NULL, "
                "priority VARCHAR NOT NULL, "
                "reasons JSON, "
                "warnings JSON, "
                "calculated_at DATETIME)"
            )
        )
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _opp(db: Session, title: str, *, status: str = "open", close_days: int | None = 30) -> str:
    close_date = (
        datetime.now(UTC).replace(tzinfo=None) + timedelta(days=close_days)
        if close_days is not None
        else None
    )
    opp = Opportunity(
        title=title,
        slug=title.lower().replace(" ", "-"),
        entity="Test Entity",
        country="Colombia",
        status=status,
        close_date=close_date,
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return opp.id


def _score(db: Session, opp_id: str, org: str, *, score: float, priority: str) -> None:
    db.add(
        OpportunityScore(
            opportunity_id=opp_id,
            organization_id=org,
            score=score,
            priority=priority,
            reasons=[],
            warnings=[],
        )
    )
    db.commit()


# ---------------------------------------------------------------------------
# 1. DISTINCT KPIs under score fan-out
# ---------------------------------------------------------------------------


def test_kpis_count_distinct_opportunities_with_duplicate_scores(legacy_db: Session) -> None:
    org = "org-1"
    dup_id = _opp(legacy_db, "Duplicated Scores Opp")
    _score(legacy_db, dup_id, org, score=80.0, priority="high")
    _score(legacy_db, dup_id, org, score=81.0, priority="high")
    _score(legacy_db, dup_id, org, score=82.0, priority="high")
    plain_id = _opp(legacy_db, "Plain Opp")
    _score(legacy_db, plain_id, org, score=40.0, priority="medium")

    kpis = dashboard_svc.get_health_kpis(legacy_db, org)

    assert kpis.total == 2
    assert kpis.open == 2
    assert kpis.high_match == 1


# ---------------------------------------------------------------------------
# 2. UniqueConstraint (opportunity_id, organization_id)
# ---------------------------------------------------------------------------


def test_opportunity_score_has_unique_constraint_metadata() -> None:
    uniques = [
        c
        for c in OpportunityScore.__table__.constraints
        if isinstance(c, UniqueConstraint)
        and {col.name for col in c.columns} == {"opportunity_id", "organization_id"}
    ]
    assert uniques, "OpportunityScore lacks UniqueConstraint(opportunity_id, organization_id)"


def test_opportunity_score_rejects_duplicate_rows(db: Session) -> None:
    opp_id = _opp(db, "Unique Score Opp")
    _score(db, opp_id, "org-1", score=80.0, priority="high")
    with pytest.raises(IntegrityError):
        _score(db, opp_id, "org-1", score=81.0, priority="high")


# ---------------------------------------------------------------------------
# 3. Coverage: same scope numerator/denominator, never > 100
# ---------------------------------------------------------------------------


def test_coverage_never_exceeds_100_with_closed_opportunities(db: Session) -> None:
    org = "org-1"
    for i in range(2):
        opp_id = _opp(db, f"Closed Opp {i}", status="closed", close_days=-5)
        db.add(OpportunityEmbedding(opportunity_id=opp_id, embedding=[0.0] * 64))
    _opp(db, "Open Opp No Embedding", status="open", close_days=30)
    db.commit()

    coverage = dashboard_svc.get_data_coverage(db, org)

    assert coverage.embeddings_coverage is not None
    assert coverage.embeddings_coverage <= 100.0
    assert coverage.embeddings_coverage == pytest.approx(66.7, abs=0.1)


# ---------------------------------------------------------------------------
# 4. Banner excludes disabled sources
# ---------------------------------------------------------------------------


def _source(db: Session, name: str, *, enabled: bool) -> str:
    source = Source(
        name=name, key=name.lower().replace(" ", "-"), base_url="https://example.com",
        enabled=enabled,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source.id


def _failed_run(db: Session, source_id: str) -> None:
    db.add(SourceRun(source_id=source_id, status="failed", items_found=0))
    db.commit()


def test_source_banner_excludes_disabled_sources(db: Session) -> None:
    org = "org-1"
    _failed_run(db, _source(db, "Disabled Broken", enabled=False))
    degraded, failing, alerts = dashboard_svc.get_source_health_summaries(db, org)
    assert (degraded, failing) == (0, 0)
    assert alerts == []

    _failed_run(db, _source(db, "Enabled Broken", enabled=True))
    degraded, failing, alerts = dashboard_svc.get_source_health_summaries(db, org)
    assert failing == 1
    assert [a.source_id for a in alerts] != []


# ---------------------------------------------------------------------------
# 5. Charts share the KPI opportunity scope
# ---------------------------------------------------------------------------


def test_charts_match_kpi_scope(db: Session) -> None:
    org = "org-1"
    _opp(db, "Open Colombia A", status="open", close_days=30)
    _opp(db, "Open Colombia B", status="open", close_days=30)
    _opp(db, "Open Brazil", status="open", close_days=30)
    _opp(db, "Closed Colombia", status="closed", close_days=-5)

    kpis = dashboard_svc.get_health_kpis(db, org)
    status_items = dashboard_svc.get_status_breakdown(db, org)
    country_items = dashboard_svc.get_country_breakdown(db, org)

    assert kpis.total == 3
    assert sum(item.total for item in status_items) == kpis.total
    assert sum(item.total for item in country_items) == kpis.total
