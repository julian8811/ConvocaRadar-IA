#!/usr/bin/env python3
"""Systematic LLM backfill of dates/funding for stored opportunities (E16).

Background: per-source scraping cannot recover what sources do not publish
structurally, so thousands of stored rows sit without open_date / close_date
/ funding. The ``POST /opportunities/reanalyze-all`` endpoint cannot fix
this: no offset, always the 500 most-recently-updated rows. This script
selects stored opportunities missing open OR close OR funding value,
oldest-first (``updated_at`` ASC, so repeated runs progress instead of
re-hitting the same rows), and runs them through
``extract_opportunity_structured`` (app/core/ai.py) on
title+description(+raw_text capped).

Gap-fill only: open/close/funding/summary are filled ONLY when the existing
value is missing — mirroring ``_update_opportunity``
(app/services/opportunity.py:605-619). Existing values are never
overwritten. LLM strings are converted with the existing parsers
(``_parse_ai_close_date``, ``_parse_ai_open_date``, ``_parse_funding_amount``)
— no new parsing invented here.

Provider note: extraction degrades to the local heuristic when no LLM is
configured (``provider == "local"``). Local-only adds nothing over existing
heuristics EXCEPT dates via regex on the full text, so local results are
still attempted but only persisted when they yield a field the row lacks
(which is exactly the gap-fill rule). The provider is logged per batch.

Usage:
    python scripts/backfill_llm_extraction.py --dry-run [--limit 100]
    python scripts/backfill_llm_extraction.py --no-dry-run --limit 200 --sleep 1.0
    python scripts/backfill_llm_extraction.py --no-dry-run --source-key grants-gov

Exit codes: 0 ok (per-row extraction failures degrade to failed/skipped),
1 on DB failure.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

# Ensure we can import from the API package (precedent: backfill_grants_gov_awards.py)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apps", "api"))

from sqlalchemy import or_, select

from app.core import ai as ai_module
from app.models import Opportunity, Source
from app.services.opportunity import (
    _parse_ai_close_date,
    _parse_ai_open_date,
    _parse_funding_amount,
)

DEFAULT_LIMIT = 100
DEFAULT_SLEEP_SECONDS = 1.0
BACKFILL_BATCH_SIZE = 5
RAW_TEXT_CAP = 8000


def build_extraction_text(opp: Opportunity) -> str:
    """Title + description + raw text (capped) for structured extraction."""
    parts = [opp.title or "", opp.description or "", (opp.raw_text or "")[:RAW_TEXT_CAP]]
    return "\n\n".join(part for part in parts if part.strip())


def parsed_fields_from_extraction(
    *, data: dict, country: str | None, url: str | None
) -> dict:
    """Convert raw LLM extraction strings into typed values.

    Reuses the existing date/funding parsers — no new parsing invented.
    """
    fields: dict = {
        "open_date": _parse_ai_open_date(data.get("open_date")),
        "close_date": _parse_ai_close_date(data.get("close_date")),
    }
    raw = data.get("funding_amount_raw")
    value, currency = (
        _parse_funding_amount(raw, country, url) if raw else (None, None)
    )
    if value is None and data.get("funding_amount_value") is not None:
        try:
            value = float(data["funding_amount_value"])
        except (TypeError, ValueError):
            value = None
        else:
            currency = data.get("funding_amount_currency")
    fields["funding_amount_raw"] = raw
    fields["funding_amount_value"] = value
    fields["funding_amount_currency"] = currency
    summary = data.get("summary")
    fields["summary"] = (
        summary.strip() if isinstance(summary, str) and summary.strip() else None
    )
    return fields


def llm_gap_fill_updates(
    *,
    existing_open=None,
    existing_close=None,
    existing_raw: str | None,
    existing_value: float | None,
    existing_currency: str | None = None,
    existing_summary: str | None,
    fields: dict,
) -> dict:
    """Pure gap-fill diff mirroring ``_update_opportunity`` exactly.

    Funding/open/close/summary keys appear in the result ONLY when the
    existing value is missing — never an overwrite. Single source of truth
    for both dry-run reporting and real updates.
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
    summary = fields.get("summary")
    if summary and not (existing_summary or "").strip():
        updates["summary"] = summary
    return updates


def apply_llm_gap_fill(opp: Opportunity, fields: dict) -> dict:
    """Apply parsed LLM fields onto a stored row, gap-fill only.

    Returns the applied updates (empty when the row had nothing missing).
    """
    updates = llm_gap_fill_updates(
        existing_open=opp.open_date,
        existing_close=opp.close_date,
        existing_raw=opp.funding_amount_raw,
        existing_value=opp.funding_amount_value,
        existing_currency=opp.funding_amount_currency,
        existing_summary=opp.summary,
        fields=fields,
    )
    for key, val in updates.items():
        setattr(opp, key, val)
    return updates


def fetch_targets(db, source_key: str | None, limit: int) -> list[Opportunity]:
    """Stored rows missing open OR close OR funding value, oldest-first.

    ``updated_at`` ASC (not DESC) so repeated runs progress through the
    backlog instead of re-hitting the same recently-touched rows — this is
    the ``reanalyze-all`` flaw being fixed.
    """
    stmt = select(Opportunity).where(
        or_(
            Opportunity.open_date.is_(None),
            Opportunity.close_date.is_(None),
            Opportunity.funding_amount_value.is_(None),
        )
    )
    if source_key:
        source_id = db.scalar(select(Source.id).where(Source.key == source_key))
        if source_id is None:
            return []
        stmt = stmt.where(Opportunity.source_id == source_id)
    stmt = stmt.order_by(Opportunity.updated_at.asc()).limit(limit)
    return list(db.scalars(stmt))


async def run_backfill(
    db,
    *,
    limit: int = DEFAULT_LIMIT,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    dry_run: bool = True,
    source_key: str | None = None,
    batch_size: int = BACKFILL_BATCH_SIZE,
    sleep_fn=None,
) -> dict:
    """Run Gemini/local extraction over stored rows missing dates/funding.

    Batches of ``batch_size`` rows go through
    ``extract_opportunity_structured`` (gap-fill only, best-effort per row),
    with a politeness sleep between batches and one commit per batch when not
    a dry-run. A dead extraction degrades to failed — the run never aborts.
    Returns ``{"scanned", "filled", "filled_dates", "filled_funding",
    "skipped", "failed", ...}``.
    """
    sleep = sleep_fn or asyncio.sleep
    targets = fetch_targets(db, source_key, limit)
    summary: dict = {
        "scanned": len(targets),
        "filled": 0,
        "filled_dates": 0,
        "filled_funding": 0,
        "skipped": 0,
        "failed": 0,
        "source_key": source_key,
        "dry_run": dry_run,
    }
    scope = source_key or "all sources"
    print(f"Found {len(targets)} opportunities missing dates/funding ({scope})")
    if not targets:
        print("Nothing to do.")
        return summary

    batches = [targets[i : i + batch_size] for i in range(0, len(targets), batch_size)]
    for index, batch in enumerate(batches):
        providers: set[str] = set()
        batch_updates: list[dict] = []
        for opp in batch:
            try:
                text = build_extraction_text(opp)
                result = await ai_module.extract_opportunity_structured(text)
            except Exception as exc:
                print(f"  row {opp.id} extraction failed ({exc}); skipping")
                summary["failed"] += 1
                continue
            providers.add(getattr(result, "provider", "?"))
            try:
                data = getattr(result, "data", None) or {}
                fields = parsed_fields_from_extraction(
                    data=data, country=opp.country, url=opp.official_url
                )
                if dry_run:
                    updates = llm_gap_fill_updates(
                        existing_open=opp.open_date,
                        existing_close=opp.close_date,
                        existing_raw=opp.funding_amount_raw,
                        existing_value=opp.funding_amount_value,
                        existing_currency=opp.funding_amount_currency,
                        existing_summary=opp.summary,
                        fields=fields,
                    )
                    if updates:
                        batch_updates.append(updates)
                        print(f"  would fill: {(opp.title or '')[:50]} ({updates.keys()})")
                    else:
                        summary["skipped"] += 1
                else:
                    updates = apply_llm_gap_fill(opp, fields)
                    if updates:
                        batch_updates.append(updates)
                        print(f"  filled: {(opp.title or '')[:50]} ({updates.keys()})")
                    else:
                        summary["skipped"] += 1
                        print(f"  no new fields: {(opp.title or '')[:50]}")
            except Exception as exc:
                print(f"  row {opp.id} failed ({exc}); skipping")
                summary["failed"] += 1
        print(
            f"  batch {index + 1}/{len(batches)} "
            f"providers={sorted(providers) if providers else ['none']}"
        )
        batch_filled = len(batch_updates)
        batch_dates = sum(
            1 for u in batch_updates if "open_date" in u or "close_date" in u
        )
        batch_funding = sum(
            1
            for u in batch_updates
            if "funding_amount_value" in u or "funding_amount_raw" in u
        )
        summary["filled"] += batch_filled
        summary["filled_dates"] += batch_dates
        summary["filled_funding"] += batch_funding
        if not dry_run:
            try:
                db.commit()
            except Exception as exc:
                db.rollback()
                print(f"  batch {index + 1} commit failed ({exc}); rolled back")
                summary["filled"] -= batch_filled
                summary["filled_dates"] -= batch_dates
                summary["filled_funding"] -= batch_funding
                summary["skipped"] += batch_filled
        if index < len(batches) - 1 and sleep_seconds > 0:
            await sleep(sleep_seconds)

    if dry_run:
        print(f"\nDry-run: {summary['filled']} opportunities would be updated")
    else:
        print(f"\nCommitted fills for {summary['filled']} opportunities")
    print(
        f"Summary: scanned={summary['scanned']} "
        f"filled_dates={summary['filled_dates']} "
        f"filled_funding={summary['filled_funding']} "
        f"skipped={summary['skipped']} failed={summary['failed']}"
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill dates/funding via structured LLM extraction"
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
    parser.add_argument(
        "--source-key",
        default=None,
        help="Scope to one source key (default: all sources)",
    )
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
            f"backfill_llm_extraction: scanned={summary['scanned']} "
            f"filled={summary['filled']} "
            f"filled_dates={summary['filled_dates']} "
            f"filled_funding={summary['filled_funding']} "
            f"skipped={summary['skipped']} failed={summary['failed']} "
            f"dry_run={args.dry_run}"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
