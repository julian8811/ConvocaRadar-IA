"""Triage, pipeline, and health dashboard queries for the review workflow.

Extracted from ``app/services/_legacy.py`` (PR B-1 series).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models import Opportunity, OpportunityScore, Source
from app.schemas import TriageOpportunityItem


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
