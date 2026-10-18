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

from app.connectors.common import enrich_from_detail_page, looks_like_news
from app.db.session import SessionLocal
from app.models import Opportunity, Source


def should_skip_opp(opp) -> bool:
    """True when a stored row is a news post, not a call (T2c).

    Same rule as the ingest filter: news-section URL + no call signal.
    Skipping here prevents the backfill from filling news rows with junk
    (GTM JS as description, phantom funding). Content alone never skips."""
    title = getattr(opp, "title", None)
    summary = getattr(opp, "summary", None) or getattr(opp, "description", None)
    url = getattr(opp, "official_url", None)
    try:
        return bool(looks_like_news(title, summary, str(url) if url else None))
    except Exception:
        return False


def parse_args(argv: list[str] | None = None) -> dict:
    """Parse CLI args. Returns dict(dry_run, limit, source_keys).

    ``--source-key`` is repeatable to scope the run to true-call sources.
    Default is dry-run ON (safe); ``--no-dry-run`` persists."""
    args = list(sys.argv[1:] if argv is None else argv)
    dry_run = True
    limit = 50
    source_keys: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--no-dry-run":
            dry_run = False
        elif arg == "--dry-run" or arg == "-n":
            dry_run = True
        elif arg.startswith("--limit="):
            limit = int(arg.split("=", 1)[1])
        elif arg == "--limit" and i + 1 < len(args):
            i += 1
            limit = int(args[i])
        elif arg.startswith("--source-key="):
            source_keys.append(arg.split("=", 1)[1])
        elif arg == "--source-key" and i + 1 < len(args):
            i += 1
            source_keys.append(args[i])
        i += 1
    return {"dry_run": dry_run, "limit": limit, "source_keys": source_keys}


async def backfill(dry_run: bool = True, limit: int = 50, source_keys: list[str] | None = None) -> int:
    """Enrich opportunities missing close_date or funding_amount.

    Returns the number of opportunities that would be / were updated.
    """
    db = SessionLocal()
    try:
        # Find opportunities that have a URL but no close_date AND no amount
        stmt = select(Opportunity).where(
            Opportunity.official_url.isnot(None),
            Opportunity.official_url != "",
            Opportunity.close_date.is_(None),
            Opportunity.funding_amount_value.is_(None),
        )
        if source_keys:
            stmt = stmt.join(Source, Opportunity.source_id == Source.id).where(
                Source.key.in_(source_keys)
            )
        stmt = stmt.order_by(Opportunity.created_at.desc()).limit(limit)
        opportunities = list(db.scalars(stmt))
        print(f"Found {len(opportunities)} opportunities to enrich")

        updated = 0
        skipped_news = 0
        for opp in opportunities:
            if should_skip_opp(opp):
                skipped_news += 1
                continue
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
            print(f"\nCommitted {updated} updates (skipped_news={skipped_news})")
        else:
            db.rollback()
            print(f"\nDry-run: {updated} opportunities would be updated (skipped_news={skipped_news})")

        return updated
    finally:
        db.close()


if __name__ == "__main__":
    _parsed = parse_args()
    print(
        f"Backfill enrichment (dry_run={_parsed['dry_run']}, "
        f"limit={_parsed['limit']}, source_keys={_parsed['source_keys'] or 'all'})"
    )
    asyncio.run(
        backfill(
            dry_run=_parsed["dry_run"],
            limit=_parsed["limit"],
            source_keys=_parsed["source_keys"] or None,
        )
    )
