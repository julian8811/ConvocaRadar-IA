#!/usr/bin/env python3
"""Backfill enrichment: fetch detail pages for existing opportunities without
close_date or funding_amount, and update them with extracted data.

Usage:
    python scripts/backfill_enrich_opportunities.py [--dry-run] [--limit 100]
"""

from __future__ import annotations

import asyncio
import os
import sys

# Ensure we can import from the API package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))

from sqlalchemy import select

from app.connectors.common import enrich_from_detail_page
from app.db.session import SessionLocal
from app.models import Opportunity


async def backfill(dry_run: bool = True, limit: int = 50) -> int:
    """Enrich opportunities missing close_date or funding_amount.

    Returns the number of opportunities that would be / were updated.
    """
    db = SessionLocal()
    try:
        # Find opportunities that have a URL but no close_date AND no amount
        stmt = (
            select(Opportunity)
            .where(
                Opportunity.official_url.isnot(None),
                Opportunity.official_url != "",
                Opportunity.close_date.is_(None),
                Opportunity.funding_amount_value.is_(None),
            )
            .order_by(Opportunity.created_at.desc())
            .limit(limit)
        )
        opportunities = list(db.scalars(stmt))
        print(f"Found {len(opportunities)} opportunities to enrich")

        updated = 0
        for opp in opportunities:
            url = str(opp.official_url)
            if not url.startswith("http"):
                continue

            print(f"  Fetching: {opp.title[:50]}...", end=" ")
            result = await enrich_from_detail_page(url)
            if not result:
                print("no data")
                continue

            # Fields we can update
            has_updates = False
            if result.get("close_date") and not opp.close_date:
                opp.close_date = result["close_date"]
                has_updates = True
            if result.get("funding_amount_raw") and not opp.funding_amount_raw:
                opp.funding_amount_raw = result["funding_amount_raw"]
                has_updates = True
            if result.get("summary") and len(result["summary"]) > len(opp.summary or ""):
                opp.summary = result["summary"][:700]
                has_updates = True

            if has_updates:
                updated += 1
                if not dry_run:
                    db.flush()
                print(f"enriched (close={bool(result.get('close_date'))}, "
                      f"amount={bool(result.get('funding_amount_raw'))})")
            else:
                print("no new fields")

        if not dry_run:
            db.commit()
            print(f"\nCommitted {updated} updates")
        else:
            db.rollback()
            print(f"\nDry-run: {updated} opportunities would be updated")

        return updated
    finally:
        db.close()


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv
    limit = 50
    for arg in sys.argv:
        if arg.startswith("--limit="):
            limit = int(arg.split("=")[1])

    print(f"Backfill enrichment (dry_run={dry_run}, limit={limit})")
    asyncio.run(backfill(dry_run=dry_run, limit=limit))
