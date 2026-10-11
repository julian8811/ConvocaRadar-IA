#!/usr/bin/env python3
"""Backfill T4 hybrid sector classification for stored opportunities.

Selects stored rows missing a sector (or holding a low-confidence one),
oldest-first (``updated_at`` ASC, so repeated runs progress through the
backlog), and runs them through ``classify_sector`` (app/core/sectors.py:
rules -> embeddings -> LLM judge). Every row stores
``sector + sector_confidence + sector_source`` (rules/embeddings/llm).

Gap-fill only: a stored sector with confidence >= 0.8 is never
reclassified unless ``--force`` (mirrors
``SECTOR_HIGH_CONFIDENCE_KEEP`` in app/core/sectors.py — single source
of truth, imported here). The LLM judge only fires on rows the cheaper
layers leave as otros/low-confidence, and abstains (no network, no key)
by keeping the earlier label — so local-only runs still persist
rules/embeddings results.

Usage:
    python scripts/backfill_sector.py --dry-run [--limit 100]
    python scripts/backfill_sector.py --no-dry-run --limit 200 --sleep 1.0
    python scripts/backfill_sector.py --no-dry-run --force --limit 500

Exit codes: 0 ok (per-row classifier failures degrade to failed/skipped),
1 on DB failure.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import os
import sys

# Ensure we can import from the API package (precedent: backfill_grants_gov_awards.py)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apps", "api"))

from sqlalchemy import or_, select

from app.core.sectors import SECTOR_HIGH_CONFIDENCE_KEEP, aclassify_sector
from app.models import Opportunity

DEFAULT_LIMIT = 100
DEFAULT_SLEEP_SECONDS = 3.0
BACKFILL_BATCH_SIZE = 20


def build_sector_text(opp: Opportunity) -> str:
    """Title + description (+ raw text capped) for sector classification."""
    parts = [opp.title or "", opp.description or "", (opp.raw_text or "")[:8000]]
    return "\n\n".join(part for part in parts if part.strip())


def needs_sector(opp: Opportunity, *, force: bool = False) -> bool:
    """Pure gap-fill predicate mirroring the backfill contract.

    Without ``--force`` a stored sector with confidence >=
    ``SECTOR_HIGH_CONFIDENCE_KEEP`` is kept; missing sectors and
    low-confidence ones are (re)classified. Single source of truth for
    both target selection and dry-run reporting.
    """
    if force:
        return True
    if not (opp.sector or "").strip():
        return True
    if opp.sector_confidence is None:
        return True
    try:
        return float(opp.sector_confidence) < SECTOR_HIGH_CONFIDENCE_KEEP
    except (TypeError, ValueError):
        return True


def fetch_targets(db, limit: int, *, force: bool = False) -> list[Opportunity]:
    """Rows needing sectorization, oldest-first.

    ``updated_at`` ASC (not DESC) so repeated runs progress through the
    backlog instead of re-hitting the same recently-touched rows.
    """
    stmt = select(Opportunity)
    if not force:
        stmt = stmt.where(
            or_(
                Opportunity.sector.is_(None),
                Opportunity.sector == "",
                Opportunity.sector_confidence.is_(None),
                Opportunity.sector_confidence < SECTOR_HIGH_CONFIDENCE_KEEP,
            )
        )
    stmt = stmt.order_by(Opportunity.updated_at.asc()).limit(limit)
    return list(db.scalars(stmt))


def _default_embed_fn():
    """Real embedding layer for the default backfill pipeline (lazy import).

    Local provider (or unconfigured remote): pure ``build_local_hash_vector``
    wrapper — loop-safe, zero network. Configured remote provider:
    ``build_embedding_sync`` (loop-unsafe on its own, but the async pipeline
    runs the embedding step in a worker thread).
    """
    from app.core import ai as _ai
    from app.core.config import get_settings

    try:
        settings = get_settings()
        dimensions = settings.embedding_dimensions or 64
        remote = (
            _ai.effective_llm_provider(settings.llm_provider) != "local"
            and bool(settings.llm_api_key)
            and bool(settings.embedding_model)
        )
    except Exception:
        dimensions = 64
        remote = False
    if remote:
        return _ai.build_embedding_sync
    return lambda text: _ai.build_local_hash_vector(text, dimensions)


async def run_backfill(
    db,
    *,
    limit: int = DEFAULT_LIMIT,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    dry_run: bool = True,
    force: bool = False,
    batch_size: int = BACKFILL_BATCH_SIZE,
    classify_fn=None,
    sleep_fn=None,
    embed_fn=None,
    llm_client=None,
) -> dict:
    """Classify stored rows missing (or unsure of) their sector.

    Rows are processed STRICTLY SEQUENTIALLY with a politeness sleep of
    ``sleep_seconds`` between EVERY row (Groq free-tier 429 protection),
    and one commit per ``batch_size`` rows (commit cadence only) when not
    a dry-run. A dead classification degrades to failed — the run never
    aborts. ``classify_fn(text) -> (sector, confidence, source)`` is
    injectable (tests pass a stub; may be sync or async) and wins over the
    default pipeline. Otherwise the default is the real async hybrid
    pipeline (``aclassify_sector``: rules -> embeddings -> LLM judge) with
    ``embed_fn`` (default: real embedding layer) and ``llm_client``
    (default: async Groq judge, abstains when unconfigured). ``embed_fn``
    maps text -> vector; ``llm_client`` is
    ``(system_prompt, user_text) -> dict | None`` (sync or async).
    Returns ``{"scanned", "filled", "skipped", "high_conf_skipped",
    "failed", "dry_run", "force"}``.
    """
    sleep = sleep_fn or asyncio.sleep
    if classify_fn is not None:
        classify = classify_fn
    else:
        _embed = embed_fn if embed_fn is not None else _default_embed_fn()
        _llm = llm_client

        async def _default_classify(text: str, _embed=_embed, _llm=_llm):
            return await aclassify_sector(text, embed_fn=_embed, llm_client=_llm)

        classify = _default_classify
    targets = fetch_targets(db, limit, force=force)
    summary: dict = {
        "scanned": len(targets),
        "filled": 0,
        "skipped": 0,
        "high_conf_skipped": 0,
        "failed": 0,
        "dry_run": dry_run,
        "force": force,
    }
    print(f"Found {len(targets)} opportunities needing sectorization")
    if not targets:
        print("Nothing to do.")
        return summary

    batches = [targets[i : i + batch_size] for i in range(0, len(targets), batch_size)]
    for index, batch in enumerate(batches):
        sources: set[str] = set()
        batch_filled = 0
        for pos, opp in enumerate(batch):
            if not needs_sector(opp, force=force):
                summary["skipped"] += 1
                summary["high_conf_skipped"] += 1
                print(f"  keep high-confidence sector: {(opp.title or '')[:50]}")
            else:
                try:
                    result = classify(build_sector_text(opp))
                    if inspect.isawaitable(result):
                        sector, confidence, source = await result
                    else:
                        sector, confidence, source = result
                except Exception as exc:
                    print(f"  row {opp.id} classification failed ({exc}); skipping")
                    summary["failed"] += 1
                else:
                    sources.add(source)
                    if dry_run:
                        batch_filled += 1
                        print(
                            f"  would fill: {(opp.title or '')[:50]} "
                            f"({sector} {confidence} {source})"
                        )
                    else:
                        opp.sector = sector
                        opp.sector_confidence = confidence
                        opp.sector_source = source
                        batch_filled += 1
                        print(
                            f"  filled: {(opp.title or '')[:50]} "
                            f"({sector} {confidence} {source})"
                        )
            is_last_row = index == len(batches) - 1 and pos == len(batch) - 1
            if not is_last_row and sleep_seconds > 0:
                await sleep(sleep_seconds)
        print(
            f"  batch {index + 1}/{len(batches)} "
            f"sources={sorted(sources) if sources else ['none']}"
        )
        summary["filled"] += batch_filled
        if not dry_run:
            try:
                db.commit()
            except Exception as exc:
                db.rollback()
                print(f"  batch {index + 1} commit failed ({exc}); rolled back")
                summary["filled"] -= batch_filled
                summary["failed"] += batch_filled

    if dry_run:
        print(f"\nDry-run: {summary['filled']} opportunities would be updated")
    else:
        print(f"\nCommitted fills for {summary['filled']} opportunities")
    print(
        f"Summary: scanned={summary['scanned']} "
        f"filled={summary['filled']} "
        f"skipped={summary['skipped']} "
        f"high_conf_skipped={summary['high_conf_skipped']} "
        f"failed={summary['failed']}"
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill hybrid sector classification (rules/embeddings/LLM)"
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
        help="Politeness delay in seconds between EVERY row (sequential pacing)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Reclassify even high-confidence (>= 0.8) stored sectors",
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
                    force=args.force,
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
            f"backfill_sector: scanned={summary['scanned']} "
            f"filled={summary['filled']} "
            f"skipped={summary['skipped']} "
            f"high_conf_skipped={summary['high_conf_skipped']} "
            f"failed={summary['failed']} "
            f"dry_run={args.dry_run} force={args.force}"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
