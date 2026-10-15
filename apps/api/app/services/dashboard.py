"""Triage, pipeline, and health dashboard queries for the review workflow.

Extracted from ``app/services/_legacy.py`` (PR B-1 series).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import Case, and_, or_, select
from sqlalchemy.orm import Session

from sqlalchemy import func

from app.models import Opportunity, OpportunityEmbedding, OpportunityScore, Source, SourceRun
from app.schemas import (
    DashboardBreakdownItem,
    DashboardDataCoverage,
    DashboardSourceAlert,
    HealthKpis,
    PipelineOpportunityItem,
    SourceHealthRead,
    TriageOpportunityItem,
)


# ---------------------------------------------------------------------------
# PR B-1a: /dashboard/triage helpers
# ---------------------------------------------------------------------------


def extract_score_reasons(value: object) -> list[str]:
    """Safely normalize an OpportunityScore.reasons value to a list[str].

    The column is declared as JSON (default=list) and is therefore expected
    to be a list[str] in the steady state. This helper is defensive and
    also handles:

    * ``None`` → ``[]``
    * empty list → ``[]``
    * JSON string (e.g. ``'["a", "b"]'``) → parsed list (invalid → ``[]``)
    * comma-separated string (e.g. ``"a, b"``) → split and trimmed tokens
    * any other unexpected type → ``[]``

    Never raises; the API contract requires ``reasons`` to be a list.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item is not None]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return []
            if isinstance(parsed, list):
                return [str(item) for item in parsed if item is not None]
            return []
        # Fallback: comma-separated string.
        return [part.strip() for part in text.split(",") if part.strip()]
    return []


def _triage_days_to_close(close_date: datetime | None) -> int | None:
    """Compute days_to_close without clamping negatives.

    Per PR B-1a spec: an opportunity that has already closed can still appear
    in closing_soon_7d as a negative number. None means no close_date at all.
    """
    if close_date is None:
        return None
    now = datetime.now(UTC).replace(tzinfo=None)
    return (close_date - now).days


def get_review_queue(
    db: Session,
    organization_id: str,
    *,
    limit: int = 8,
) -> list[TriageOpportunityItem]:
    """Return up to ``limit`` items the user has marked for review or kept.

    Filter: ``Opportunity.organization_id == org_id`` AND
            ``Opportunity.user_status IN ('review', 'kept')`` AND
            ``Opportunity.close_date >= today_start``.
    Order: ``close_date ASC NULLS LAST`` (soonest first).
    Score: joined from ``OpportunityScore`` for the given org, if any.
    """
    today_start = (
        datetime.now(UTC).replace(tzinfo=None).replace(hour=0, minute=0, second=0, microsecond=0)
    )
    stmt = (
        select(Opportunity, OpportunityScore, Source)
        .outerjoin(
            OpportunityScore,
            and_(
                OpportunityScore.opportunity_id == Opportunity.id,
                OpportunityScore.organization_id == organization_id,
            ),
        )
        .outerjoin(Source, Source.id == Opportunity.source_id)
        .where(
            Opportunity.organization_id == organization_id,
            Opportunity.user_status.in_(["review", "kept"]),
            Opportunity.close_date >= today_start,
        )
        .order_by(Opportunity.close_date.asc().nullslast())
        .limit(limit)
    )
    rows = list(db.execute(stmt))
    items: list[TriageOpportunityItem] = []
    for opportunity, score, source in rows:
        items.append(
            TriageOpportunityItem(
                id=opportunity.id,
                title=opportunity.title,
                country=opportunity.country,
                currency=opportunity.funding_amount_currency,
                funding_amount=opportunity.funding_amount_value,
                days_to_close=_triage_days_to_close(opportunity.close_date),
                score=score.score if score else None,
                source_key=source.key if source else None,
            )
        )
    return items


def get_closing_soon_7d(
    db: Session,
    organization_id: str,
    *,
    limit: int = 8,
) -> list[TriageOpportunityItem]:
    """Return up to ``limit`` items closing within 7 days (any user_status).

    Filter: ``Opportunity.organization_id == org_id OR
            Opportunity.organization_id IS NULL`` AND
            ``Opportunity.close_date IS NOT NULL`` AND
            ``now <= Opportunity.close_date <= now + 7 days``.
    Order: ``close_date ASC NULLS LAST``.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = now + timedelta(days=7)
    stmt = (
        select(Opportunity, OpportunityScore, Source)
        .outerjoin(
            OpportunityScore,
            and_(
                OpportunityScore.opportunity_id == Opportunity.id,
                OpportunityScore.organization_id == organization_id,
            ),
        )
        .outerjoin(Source, Source.id == Opportunity.source_id)
        .where(
            or_(
                Opportunity.organization_id == organization_id,
                Opportunity.organization_id.is_(None),
            ),
            Opportunity.close_date.is_not(None),
            Opportunity.close_date >= today_start,
            Opportunity.close_date <= cutoff,
        )
        .order_by(Opportunity.close_date.asc().nullslast())
        .limit(limit)
    )
    rows = list(db.execute(stmt))
    items: list[TriageOpportunityItem] = []
    for opportunity, score, source in rows:
        items.append(
            TriageOpportunityItem(
                id=opportunity.id,
                title=opportunity.title,
                country=opportunity.country,
                currency=opportunity.funding_amount_currency,
                funding_amount=opportunity.funding_amount_value,
                days_to_close=_triage_days_to_close(opportunity.close_date),
                score=score.score if score else None,
                source_key=source.key if source else None,
            )
        )
    return items


# Local mirror of STATUS_LABELS in app.api.v1.dashboard — kept here so the
# service layer does not depend on the route module. (Mirrored, not imported,
# to avoid the circular import risk that route→service→route would create.)
_STATUS_LABELS = {
    "open": "Abiertas",
    "closing_soon": "Cierran pronto",
    "closed": "Cerradas",
    "unknown": "Sin fecha",
}

# ---------------------------------------------------------------------------
# PR B-1b: /dashboard/pipeline helpers
# ---------------------------------------------------------------------------


def _pipeline_days_to_close(close_date: datetime | None) -> int | None:
    """Compute days_to_close clamped to >= 0 (matches PipelineRead contract).

    Differs from ``_triage_days_to_close`` which can return negative values:
    pipeline closing_soon MUST NOT include already-closed items, so the
    contract is "today or later" only. The function still returns ``None``
    when there is no close_date at all.
    """
    if close_date is None:
        return None
    now = datetime.now(UTC).replace(tzinfo=None)
    days = (close_date - now).days
    return max(days, 0)


def get_top_scored(
    db: Session,
    organization_id: str,
    *,
    limit: int = 8,
) -> list[PipelineOpportunityItem]:
    """Return up to ``limit`` highest-scoring opportunities for the org.

    Filter: scored rows for the given org whose underlying opportunity is
    visible to the org scope. Each item carries the OpportunityScore
    ``score`` (float) and ``reasons`` (list[str], normalized via
    ``extract_score_reasons``) so the UI can explain why the score is what
    it is.

    Order: ``OpportunityScore.score DESC, OpportunityScore.calculated_at DESC``.
    """
    stmt = (
        select(Opportunity, OpportunityScore, Source)
        .join(
            OpportunityScore,
            and_(
                OpportunityScore.opportunity_id == Opportunity.id,
                OpportunityScore.organization_id == organization_id,
            ),
        )
        .outerjoin(Source, Source.id == Opportunity.source_id)
        .where(
            or_(
                Opportunity.organization_id == organization_id,
                Opportunity.organization_id.is_(None),
            )
        )
        .order_by(OpportunityScore.score.desc(), OpportunityScore.calculated_at.desc())
        .limit(limit)
    )
    items: list[PipelineOpportunityItem] = []
    for opportunity, score, source in db.execute(stmt):
        items.append(
            PipelineOpportunityItem(
                id=opportunity.id,
                title=opportunity.title,
                country=opportunity.country,
                currency=opportunity.funding_amount_currency,
                funding_amount=opportunity.funding_amount_value,
                days_to_close=_pipeline_days_to_close(opportunity.close_date),
                score=score.score,
                reasons=extract_score_reasons(score.reasons),
                source_key=source.key if source else None,
            )
        )
    return items


def get_closing_soon(
    db: Session,
    organization_id: str,
    *,
    limit: int = 8,
    days_window: int = 30,
) -> list[PipelineOpportunityItem]:
    """Return up to ``limit`` items closing within the ``days_window``.

    Filter: ``close_date IS NOT NULL`` AND
            ``(Opportunity.organization_id == org_id OR IS NULL)`` AND
            ``close_date`` falls on a day in ``[today, today + days_window]``.

    The lower bound uses day-granularity (start of today) so an opportunity
    that closes later today (close_date = now + 0 days) is included even if
    the row was written a few milliseconds before the request — the
    ``days_to_close`` field is exposed as an integer day count and 0 must
    mean "today", not "in the past".

    Order: ``close_date ASC NULLS LAST`` (soonest first; NULLs are already
    filtered out by the ``IS NOT NULL`` predicate).
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # Upper bound is exclusive of the next day: an item closing any time
    # during the Nth day from today (where N = days_window) is included,
    # but not anything on the (N+1)th day. This matches the contract
    # ``0 <= days_to_close <= days_window`` under day-truncated math.
    cutoff_exclusive = today_start + timedelta(days=days_window + 1)
    stmt = (
        select(Opportunity, OpportunityScore, Source)
        .outerjoin(
            OpportunityScore,
            and_(
                OpportunityScore.opportunity_id == Opportunity.id,
                OpportunityScore.organization_id == organization_id,
            ),
        )
        .outerjoin(Source, Source.id == Opportunity.source_id)
        .where(
            or_(
                Opportunity.organization_id == organization_id,
                Opportunity.organization_id.is_(None),
            ),
            Opportunity.close_date.is_not(None),
            Opportunity.close_date >= today_start,
            Opportunity.close_date < cutoff_exclusive,
        )
        .order_by(Opportunity.close_date.asc().nullslast())
        .limit(limit)
    )
    items: list[PipelineOpportunityItem] = []
    for opportunity, score, source in db.execute(stmt):
        items.append(
            PipelineOpportunityItem(
                id=opportunity.id,
                title=opportunity.title,
                country=opportunity.country,
                currency=opportunity.funding_amount_currency,
                funding_amount=opportunity.funding_amount_value,
                days_to_close=_pipeline_days_to_close(opportunity.close_date),
                score=score.score if score else None,
                reasons=[],
                source_key=source.key if source else None,
            )
        )
    return items


# ---------------------------------------------------------------------------
# PR B-1c: /dashboard/health helpers
# ---------------------------------------------------------------------------


def _opportunity_scope(organization_id: str):
    """Shared visibility scope for KPI and chart queries (R1).

    An opportunity is in scope when it belongs to the org (or is global),
    is not past its deadline, and is not a scraping-noise row. Charts reuse
    this exact scope so their totals add up to the KPI total.
    """
    return and_(
        or_(Opportunity.organization_id == organization_id, Opportunity.organization_id.is_(None)),
        or_(
            Opportunity.close_date.is_(None),
            Opportunity.close_date >= datetime.now(UTC).replace(tzinfo=None),
        ),
        ~Opportunity.title.ilike("%@%"),
        ~Opportunity.title.ilike("http%"),
        ~Opportunity.title.ilike("%color:%"),
        ~Opportunity.title.ilike("%background-color:%"),
        ~Opportunity.title.ilike("%font-weight:%"),
        ~Opportunity.title.ilike("%display:%"),
        ~Opportunity.title.ilike("%justify-content:%"),
        ~Opportunity.title.ilike("%budgetYearsColumns%"),
        ~Opportunity.title.ilike("%plannedOpeningDate%"),
        ~Opportunity.title.ilike("%deadlineDate%"),
        ~Opportunity.title.ilike("%expectedGrants%"),
    )


def get_health_kpis(db: Session, organization_id: str) -> HealthKpis:
    """Return the 4 KPI counts that drive the Health zone summary.

    * total: every opportunity visible to the org scope.
    * open: opportunities with status='open'.
    * closing_soon: opportunities with status='closing_soon'.
    * high_match: distinct opportunities with an OpportunityScore row
      marked priority='high' for the current org.

    All counts use ``COUNT(DISTINCT Opportunity.id)``: the ``LEFT JOIN``
    against ``OpportunityScore`` fans out one row per score, and duplicate
    score rows may still exist from before migration 0018 (unique
    constraint + server-side cleanup), so a plain ``COUNT(*)`` inflates
    totals. Uses a single combined query with CASE expressions instead of
    4 separate ``count_query`` calls.
    """
    opportunity_scope = _opportunity_scope(organization_id)
    stmt = (
        select(
            func.count(func.distinct(Opportunity.id)).label("total"),
            func.count(
                func.distinct(
                    Case((Opportunity.status == "open", Opportunity.id), else_=None)
                )
            ).label("open"),
            func.count(
                func.distinct(
                    Case((Opportunity.status == "closing_soon", Opportunity.id), else_=None)
                )
            ).label("closing_soon"),
            func.count(
                func.distinct(
                    Case(
                        (OpportunityScore.priority == "high", OpportunityScore.opportunity_id),
                        else_=None,
                    )
                )
            ).label("high_match"),
        )
        .select_from(Opportunity)
        .outerjoin(
            OpportunityScore,
            and_(
                OpportunityScore.opportunity_id == Opportunity.id,
                OpportunityScore.organization_id == organization_id,
            ),
        )
        .where(opportunity_scope)
    )

    row = db.execute(stmt).one()
    return HealthKpis(
        total=row.total,
        open=row.open,
        closing_soon=row.closing_soon,
        high_match=row.high_match,
    )


def get_status_breakdown(db: Session, organization_id: str) -> list[DashboardBreakdownItem]:
    """Group opportunities by status; return ``[{name, total}, ...]`` sorted desc.

    Uses the same ``_opportunity_scope`` as the KPIs (deadline + noise
    filters) so the breakdown totals add up to the KPI total.
    """
    opportunity_scope = _opportunity_scope(organization_id)
    rows = db.execute(
        select(Opportunity.status, func.count())
        .where(opportunity_scope)
        .group_by(Opportunity.status)
    )
    items = [
        DashboardBreakdownItem(name=_STATUS_LABELS.get(status, status), total=total)
        for status, total in rows
        if total > 0
    ]
    items.sort(key=lambda item: item.total, reverse=True)
    return items


def get_country_breakdown(db: Session, organization_id: str) -> list[DashboardBreakdownItem]:
    """Top-8 country counts; rows with empty country bucket under "Sin dato"."""
    opportunity_scope = _opportunity_scope(organization_id)
    rows = db.execute(
        select(Opportunity.country, func.count())
        .where(opportunity_scope)
        .group_by(Opportunity.country)
        .order_by(func.count().desc())
        .limit(8)
    )
    return [
        DashboardBreakdownItem(name=country or "Sin dato", total=total)
        for country, total in rows
        if total > 0
    ]


def get_data_coverage(db: Session, organization_id: str) -> DashboardDataCoverage:
    """Build the data-coverage strip; ``embeddings_coverage`` is now nullable.

    Scope choice (R1): numerator and denominator share the plain org scope
    with NO deadline filter, matching ``GET /admin/metrics``
    (``admin.py``). Coverage measures catalog completeness, not the
    open/visible set the KPIs use — applying the KPI deadline filter to
    only one side is what produced >100% values. The ratio is defensively
    clamped at 100.0 (Python ``min``, equivalent to SQL ``LEAST``, kept
    DB-agnostic since SQLite has no ``LEAST``).

    The embeddings field is ``None`` (not 0.0) when there are zero
    opportunities so a fresh org does not look "broken" — the frontend
    renders "Sin datos aún" for the None case. When opportunities exist
    but none have embeddings, the value is the real zero (``0.0``).
    """

    opportunity_scope = or_(
        Opportunity.organization_id == organization_id, Opportunity.organization_id.is_(None)
    )
    with_summary = (
        db.scalar(
            select(func.count())
            .select_from(Opportunity)
            .where(opportunity_scope, Opportunity.summary != "", Opportunity.summary.is_not(None))
        )
        or 0
    )
    with_amount = (
        db.scalar(
            select(func.count())
            .select_from(Opportunity)
            .where(
                opportunity_scope,
                or_(
                    Opportunity.funding_amount_value.is_not(None),
                    Opportunity.funding_amount_raw.is_not(None),
                ),
            )
        )
        or 0
    )
    with_close_date = (
        db.scalar(
            select(func.count())
            .select_from(Opportunity)
            .where(opportunity_scope, Opportunity.close_date.is_not(None))
        )
        or 0
    )
    with_source = (
        db.scalar(
            select(func.count())
            .select_from(Opportunity)
            .where(opportunity_scope, Opportunity.source_id.is_not(None))
        )
        or 0
    )
    total_opportunities = (
        db.scalar(
            select(func.count()).select_from(Opportunity).where(opportunity_scope)
        )
        or 0
    )
    embeddings_total = (
        db.scalar(
            select(func.count())
            .select_from(OpportunityEmbedding)
            .join(Opportunity, Opportunity.id == OpportunityEmbedding.opportunity_id)
            .where(opportunity_scope)
        )
        or 0
    )
    embeddings_coverage: float | None = (
        min(round((embeddings_total / total_opportunities) * 100, 1), 100.0)
        if total_opportunities
        else None
    )
    return DashboardDataCoverage(
        with_summary=with_summary,
        with_amount=with_amount,
        with_close_date=with_close_date,
        with_source=with_source,
        embeddings_coverage=embeddings_coverage,
    )


def get_sources_health(db: Session, organization_id: str) -> list[SourceHealthRead]:
    """Build a full ``SourceHealthRead`` entry for every source visible to the org.

    The per-source health is computed by the same helper that backs
    ``GET /sources/health``; we import it lazily to avoid the route →
    service → route circular dependency.

    Perf: runs and coverage ratios are preloaded in bulk (2 queries for the
    whole catalog) instead of ~5 per source.
    """
    from app.api.v1.sources import (  # lazy: avoid circular import
        _load_recent_runs_for_sources,
        _source_coverage_ratios_many,
        _source_health,
    )

    source_scope = or_(Source.organization_id == organization_id, Source.organization_id.is_(None))
    sources = list(db.scalars(select(Source).where(source_scope)))
    runs_by_source = _load_recent_runs_for_sources(db, sources)
    coverage_by_source = _source_coverage_ratios_many(db, [s.id for s in sources])
    return [
        _source_health(
            db,
            source,
            runs_by_source.get(source.id, []),
            coverage=coverage_by_source.get(source.id),
        )
        for source in sources
    ]


def get_source_health_summaries(
    db: Session, organization_id: str
) -> tuple[int, int, list[DashboardSourceAlert]]:
    """Return (degraded_count, failing_count, top-5 alerts) for the org's sources.

    Only ENABLED sources are counted: a disabled source cannot produce new
    data, so its stale/failed state is not actionable and must not inflate
    the banner. Unifying this count with ``GET /sources/health`` (which
    also surfaces ``idle``) is R3 scope and intentionally untouched here.

    Stale criterion (from ``admin._source_health_status``): a source is
    stale when days since last success >= its frequency window
    (hourly→1d, daily→3d, weekly→10d, monthly→40d, default→7d);
    ``failing`` at 2x the window or when the latest run failed.

    Mirrors the legacy /summary's source-health counts. The alerts list
    is capped at 5 entries per the original contract so the e2e and any
    client still consuming the merged summary see the same shape.
    """
    from app.api.v1.admin import _source_health_status  # lazy: avoid circular import
    from app.api.v1.sources import (  # lazy: avoid circular import
        _load_recent_runs_for_sources as _batch_runs,
    )

    source_scope = or_(Source.organization_id == organization_id, Source.organization_id.is_(None))
    sources = list(db.scalars(select(Source).where(source_scope, Source.enabled.is_(True))))

    # Batch-load the latest 10 SourceRun per source (single query instead of N+1).
    runs_by_source = _batch_runs(db, sources)

    degraded = 0
    failing = 0
    alerts: list[DashboardSourceAlert] = []
    for source in sources:
        health = _source_health_status(db, source, runs_by_source.get(source.id, []))
        if health == "degraded":
            degraded += 1
            if len(alerts) < 5:
                alerts.append(
                    DashboardSourceAlert(source_id=source.id, name=source.name, status="degraded")
                )
        elif health == "failing":
            failing += 1
            if len(alerts) < 5:
                alerts.append(
                    DashboardSourceAlert(source_id=source.id, name=source.name, status="failing")
                )
    return degraded, failing, alerts
