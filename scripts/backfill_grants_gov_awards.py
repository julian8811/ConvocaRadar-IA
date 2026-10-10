#!/usr/bin/env python3
"""Backfill grants-gov award funding for stored opportunities.

Background: ``enrich_grants_gov_funding_xhr`` (app/connectors/grants_gov.py)
fetches awards via a keyless form POST and gap-fills funding, but per-run caps
plus a fixed top-25 list mean older stored grants-gov rows never get attempted.
This script selects stored grants-gov opportunities missing funding value
and raw, and runs them through that same XHR enrich path in
small batches, with a politeness delay between batches and a commit per batch.

Gap-fill only: funding/open/close are filled ONLY when the existing value is
missing — mirroring ``_update_opportunity`` (app/services/opportunity.py).
Existing funding/dates are never overwritten.

Single-source only by design (``--source-key``, default ``grants-gov``).

Usage:
    python scripts/backfill_grants_gov_awards.py --dry-run [--limit 25]
    python scripts/backfill_grants_gov_awards.py --no-dry-run --limit 50 --sleep 1.5

Exit codes: 0 ok (per-row XHR misses degrade to skipped), 1 on
DB/connectivity failure.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

# Ensure we can import from the API package (precedent: backfill_enrich_opportunities.py)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apps", "api"))

from sqlalchemy import select

from app.connectors.base import OpportunityCandidate
from app.connectors.grants_gov import enrich_grants_gov_funding_xhr
from app.models import Opportunity, Source

DEFAULT_SOURCE_KEY = "grants-gov"
DEFAULT_LIMIT = 25
DEFAULT_SLEEP_SECONDS = 1.0
BACKFILL_BATCH_SIZE = 5


def opp_to_candidate(opp: Opportunity) -> OpportunityCandidate:
    """Project a stored row onto the candidate shape the XHR enrich expects."""
    return OpportunityCandidate(
        title=opp.title or "Untitled",
        entity=opp.entity or "Unknown",
        country=opp.country or "United States",
        official_url=opp.official_url or "",
        summary=opp.summary or "",
        description=opp.description or "",
        raw_text=opp.raw_text or "",
        confidence_score=opp.confidence_score or 0.5,
        open_date=opp.open_date,
        close_date=opp.close_date,
        funding_amount_raw=opp.funding_amount_raw,
        funding_amount_value=opp.funding_amount_value,
        funding_amount_currency=opp.funding_amount_currency,
        external_id=opp.external_id,
    )


def award_gap_fill_updates(
    *,
    existing_raw: str | None,
    existing_value: float | None,
    existing_open=None,
    existing_close=None,
    fields: dict,
) -> dict:
    """Pure gap-fill diff mirroring ``_update_opportunity`` exactly.

    Funding/open/close keys appear in the result ONLY when the existing value
    is missing — never an overwrite. Single source of truth for both dry-run
    reporting and real updates.
    """
    updates: dict = {}
    value = fields.get("funding_amount_value")
    raw = fields.get("funding_amount_raw")
    if value is not None and existing_value is None:
        updates["funding_amount_value"] = value
        updates["funding_amount_currency"] = fields.get("funding_amount_currency")
        if raw is not None:
            updates["funding_amount_raw"] = raw
    elif raw is not None and existing_raw is None:
        updates["funding_amount_raw"] = raw
        if value is not None and existing_value is None:
            updates["funding_amount_value"] = value
            updates["funding_amount_currency"] = fields.get("funding_amount_currency")
    if fields.get("open_date") is not None and existing_open is None:
        updates["open_date"] = fields["open_date"]
    if fields.get("close_date") is not None and existing_close is None:
        updates["close_date"] = fields["close_date"]
    return updates


def apply_award_gap_fill(opp: Opportunity, fields: dict) -> bool:
    """Apply award fields onto a stored row, gap-fill only. Returns changed."""
    updates = award_gap_fill_updates(
        existing_raw=opp.funding_amount_raw,
        existing_value=opp.funding_amount_value,
        existing_open=opp.open_date,
        existing_close=opp.close_date,
        fields=fields,
    )
    for key, val in updates.items():
        setattr(opp, key, val)
    return bool(updates)


def fetch_targets(db, source_key: str, limit: int) -> list[Opportunity]:
    """Stored ``source_key`` rows missing funding value AND raw, newest first.

    Both must be missing to match ``_candidate_needs_detail_xhr``: the shared
    XHR enrich path skips any candidate that already carries funding, so
    raw-only or value-only rows would never gain anything from a fetch.
    """
    source_id = db.scalar(select(Source.id).where(Source.key == source_key))
    if source_id is None:
        return []
    stmt = (
        select(Opportunity)
        .where(
            Opportunity.source_id == source_id,
            Opportunity.funding_amount_value.is_(None),
            Opportunity.funding_amount_raw.is_(None),
        )
        .order_by(Opportunity.created_at.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))


async def run_backfill(
    db,
    *,
    limit: int = DEFAULT_LIMIT,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    dry_run: bool = True,
    source_key: str = DEFAULT_SOURCE_KEY,
    batch_size: int = BACKFILL_BATCH_SIZE,
    sleep_fn=None,
) -> dict:
    """Enrich unfunded stored rows via the grants-gov detail XHR.

    Batches of ``batch_size`` candidates go through
    ``enrich_grants_gov_funding_xhr`` (gap-fill only, best-effort per row),
    with a politeness sleep between batches and one commit per batch when not
    a dry-run. A dead batch or a single bad row degrades to skipped — the run
    never aborts. Returns ``{"attempted", "filled", "skipped", ...}``.
    """
    sleep = sleep_fn or asyncio.sleep
    targets = fetch_targets(db, source_key, limit)
    summary: dict = {
        "attempted": 0,
        "filled": 0,
        "skipped": 0,
        "source_key": source_key,
        "dry_run": dry_run,
    }
    print(f"Found {len(targets)} {source_key} opportunities missing funding")
    if not targets:
        print("Nothing to do.")
        return summary

    batches = [targets[i : i + batch_size] for i in range(0, len(targets), batch_size)]
    for index, batch in enumerate(batches):
        before = [opp_to_candidate(opp) for opp in batch]
        try:
            enriched = await enrich_grants_gov_funding_xhr(before)
        except Exception as exc:  # enrich is best-effort; belt and suspenders
            print(f"  batch {index + 1}/{len(batches)} failed ({exc}); skipping")
            summary["attempted"] += len(batch)
            summary["skipped"] += len(batch)
            continue
        batch_filled = 0
        for opp, old, new in zip(batch, before, enriched):
            summary["attempted"] += 1
            try:
                fields = {
                    "funding_amount_raw": new.funding_amount_raw,
                    "funding_amount_value": new.funding_amount_value,
                    "funding_amount_currency": new.funding_amount_currency,
                    "open_date": new.open_date,
                    "close_date": new.close_date,
                }
                if dry_run:
                    updates = award_gap_fill_updates(
                        existing_raw=old.funding_amount_raw,
                        existing_value=old.funding_amount_value,
                        existing_open=old.open_date,
                        existing_close=old.close_date,
                        fields=fields,
                    )
                    if updates:
                        batch_filled += 1
                        print(f"  would fill: {old.title[:50]} ({updates.keys()})")
                    else:
                        summary["skipped"] += 1
                elif apply_award_gap_fill(opp, fields):
                    batch_filled += 1
                    print(f"  filled: {old.title[:50]}")
                else:
                    summary["skipped"] += 1
                    print(f"  no award data: {old.title[:50]}")
            except Exception as exc:
                print(f"  row {opp.id} failed ({exc}); skipping")
                summary["skipped"] += 1
        summary["filled"] += batch_filled
        if not dry_run:
            try:
                db.commit()
            except Exception as exc:
                db.rollback()
                print(f"  batch {index + 1} commit failed ({exc}); rolled back")
                summary["filled"] -= batch_filled
                summary["skipped"] += batch_filled
        if index < len(batches) - 1 and sleep_seconds > 0:
            await sleep(sleep_seconds)

    if dry_run:
        print(f"\nDry-run: {summary['filled']} opportunities would be updated")
    else:
        print(f"\nCommitted fills for {summary['filled']} opportunities")
    print(
        f"Summary: attempted={summary['attempted']} "
        f"filled={summary['filled']} skipped={summary['skipped']}"
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill grants-gov award funding via the keyless detail XHR"
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Report what would change without writing (default: on). "
        "Use --no-dry-run to persist.",
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument(
        "--sleep",
        dest="sleep_seconds",
        type=float,
        default=DEFAULT_SLEEP_SECONDS,
        help="Politeness delay in seconds between batches",
    )
    parser.add_argument("--source-key", default=DEFAULT_SOURCE_KEY)
    args = parser.parse_args(argv)
    if args.limit < 0:
        parser.error("--limit must be >= 0")
    if args.sleep_seconds < 0:
        parser.error("--sleep must be >= 0")

    from app.db.session import SessionLocal

    try:
        db = SessionLocal()
    except Exception as exc:
        print(f"DB connection failed: {exc}", file=sys.stderr)
        return 1
    try:
        try:
            summary = asyncio.run(
                run_backfill(
                    db,
                    limit=args.limit,
                    sleep_seconds=args.sleep_seconds,
                    dry_run=args.dry_run,
                    source_key=args.source_key,
                )
            )
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            print(f"backfill failed: {exc}", file=sys.stderr)
            return 1
        print(
            f"backfill_grants_gov_awards: attempted={summary['attempted']} "
            f"filled={summary['filled']} skipped={summary['skipped']} "
            f"dry_run={args.dry_run}"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
