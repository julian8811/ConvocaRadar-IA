"""CLI to backfill close_date for opportunities that are missing it.

Scans every opportunity where ``close_date IS NULL`` and attempts to
extract a close date from the stored text fields (title + summary +
description + raw_text) using the same regex-based ``extract_close_date``
function used during scraping. Also recalculates ``status`` based on the
newfound date.

Usage:
    convocaradar-backfill-close-dates
    convocaradar-backfill-close-dates --dry-run    # preview only
    convocaradar-backfill-close-dates --batch-size 100
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime

from sqlalchemy import func, select, update

from app.connectors.common import extract_close_date
from app.db.session import SessionLocal
from app.models import Opportunity
from app.services import inferred_opportunity_status


def _combined_text(opp: Opportunity) -> str:
    return " ".join(
        part
        for part in [opp.title, opp.summary, opp.description, opp.raw_text]
        if part
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill close_date for opportunities that are missing it",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without making changes",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Number of records to process per batch (default: 200)",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        total = db.scalar(
            select(func.count()).select_from(Opportunity).where(Opportunity.close_date.is_(None))
        )
        if total is None or total == 0:
            print("✓ No opportunities missing close_date — nothing to do.")
            sys.exit(0)

        print(f"📋 Found {total} opportunities without close_date")

        if args.dry_run:
            # Sample a few to show what would be extracted
            samples = (
                db.execute(
                    select(Opportunity)
                    .where(Opportunity.close_date.is_(None))
                    .order_by(Opportunity.created_at.desc())
                    .limit(5)
                )
                .scalars()
                .all()
            )
            print(f"\nSample of {len(samples)} opportunities (dry-run):")
            for opp in samples:
                text = _combined_text(opp)
                found = extract_close_date(text)
                print(
                    f"  • {opp.title[:60]}..."
                    f"  → extracted: {found.date() if found else 'None'}"
                )
            print(f"\nRun without --dry-run to apply changes to all {total} records.")
            sys.exit(0)

        # Process in batches
        processed = 0
        updated = 0
        errors = 0
        offset = 0
        batch = args.batch_size

        while True:
            rows = (
                db.execute(
                    select(Opportunity)
                    .where(Opportunity.close_date.is_(None))
                    .order_by(Opportunity.created_at.desc())
                    .offset(offset)
                    .limit(batch)
                )
                .scalars()
                .all()
            )
            if not rows:
                break

            for opp in rows:
                try:
                    text = _combined_text(opp)
                    parsed = extract_close_date(text)
                    if parsed:
                        opp.close_date = parsed
                        opp.status = inferred_opportunity_status(
                            parsed,
                            " ".join([opp.summary or "", opp.raw_text or ""]),
                        )
                        opp.updated_at = datetime.now(UTC).replace(tzinfo=None)
                        updated += 1
                except Exception as exc:
                    errors += 1
                    print(f"  ⚠ Error processing {opp.id}: {exc}", file=sys.stderr)

            db.commit()
            processed += len(rows)
            offset += len(rows)
            print(f"  ✓ {processed}/{total} processed — {updated} updated, {errors} errors")

            if len(rows) < batch:
                break

        print(f"\n✅ Done: {processed} processed, {updated} updated, {errors} errors")
        if updated:
            print(f"   {total - updated} opportunities still without close_date")
        sys.exit(0)
    finally:
        db.close()


if __name__ == "__main__":
    main()
