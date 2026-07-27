"""Triage, pipeline, and health dashboard queries for the review workflow.

Extracted from ``app/services/_legacy.py`` (PR B-1 series).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models import Opportunity, OpportunityScore, Source
from app.schemas import PipelineOpportunityItem, TriageOpportunityItem


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
    today_start = datetime.now(UTC).replace(tzinfo=None).replace(hour=0, minute=0, second=0, microsecond=0)
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
