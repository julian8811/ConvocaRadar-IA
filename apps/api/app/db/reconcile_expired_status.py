"""Conservative reconciliation of expired ConvocaRadar status labels.

Dry-run by default. An explicit --apply and exact --expected-count are
required for changes. This updates status only; no dates, amounts, URLs,
source ownership or document evidence are rewritten.

IMPORTANT: inferred closure from stored deadline is NOT independent
confirmation of closure by the funder; check official extensions separately.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, time

from sqlalchemy import func, select, update

TARGET_STATUSES = ("open", "closing_soon")


def cutoff_for_previous_dates(now: datetime | None = None) -> datetime:
    """Exclude all deadlines dated today UTC (stored datetimes are naive UTC)."""
    observed = now or datetime.now(UTC)
    if observed.tzinfo is None:
        raise ValueError("A timezone-aware instant is required")
    return datetime.combine(observed.astimezone(UTC).date(), time.min)


def candidate_filter(model, cutoff: datetime):
    return (
        model.status.in_(TARGET_STATUSES),
        model.close_date.is_not(None),
        model.close_date < cutoff,
    )


def reconcile(
    db, *, apply: bool, expected_count: int | None = None,
    max_changes: int = 400, now: datetime | None = None,
) -> dict:
    from app.models import Opportunity, Source

    cutoff = cutoff_for_previous_dates(now)
    where = candidate_filter(Opportunity, cutoff)
    count = db.scalar(select(func.count()).select_from(Opportunity).where(*where)) or 0
    groups = db.execute(
        select(func.coalesce(Source.key, "SIN_FUENTE"), func.count())
        .select_from(Opportunity)
        .outerjoin(Source, Opportunity.source_id == Source.id)
        .where(*where)
        .group_by(Source.key)
        .order_by(func.count().desc())
        .limit(20)
    ).all()
    result = {
        "cutoff_utc_date": cutoff.date().isoformat(),
        "candidates": count,
        "top_sources": [(key, qty) for key, qty in groups],
        "applied": False,
        "updated": 0,
    }
    if not apply:
        db.rollback()
        return result
    if expected_count is None:
        db.rollback()
        raise ValueError("--apply requires --expected-count")
    if count != expected_count:
        db.rollback()
        raise ValueError(f"Refusing update: expected {expected_count}, observed {count}")
    if count > max_changes:
        db.rollback()
        raise ValueError(f"Refusing update: {count} exceeds --max-changes {max_changes}")

    change = db.execute(
        update(Opportunity)
        .where(*where)
        .values(status="closed")
        .execution_options(synchronize_session=False)
    )
    if change.rowcount != count:
        db.rollback()
        raise RuntimeError(f"Concurrent change: updated {change.rowcount}, expected {count}")
    db.commit()
    result.update(applied=True, updated=change.rowcount)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Commit verified update")
    parser.add_argument("--expected-count", type=int, default=None)
    parser.add_argument("--max-changes", type=int, default=400)
    args = parser.parse_args()
    if args.max_changes < 0 or (args.expected_count is not None and args.expected_count < 0):
        parser.error("Counts must be nonnegative")

    from app.db.session import SessionLocal
    with SessionLocal() as db:
        result = reconcile(
            db, apply=args.apply, expected_count=args.expected_count,
            max_changes=args.max_changes,
        )
    print("Deadline boundary (UTC date):", result["cutoff_utc_date"])
    print("Candidates:", result["candidates"])
    for source, qty in result["top_sources"]:
        print(f"  {source:<36} {qty:>5}")
    print("Applied:", result["applied"], "Records updated:", result["updated"])
    if not args.apply:
        print("PREVIEW ONLY: database unchanged")


if __name__ == "__main__":
    main()
