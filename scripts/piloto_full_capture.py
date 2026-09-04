#!/usr/bin/env python3
"""piloto_full_capture — 20-row dry-run harness for full field capture (025 / 024 absorb).

Prefer filler sources (configurable/generic/rss/api/grants_gov). Default is dry-run;
pass --execute to persist IS-NULL / longer-text merges. Concurrency capped at 2.
Heuristics only — never EXTRACTION_LLM_ALWAYS / enrich_opportunity_payload.

Usage:
    python scripts/piloto_full_capture.py                 # dry-run, limit 20
    python scripts/piloto_full_capture.py --limit 20
    python scripts/piloto_full_capture.py --execute        # persist deltas
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

DEFAULT_LIMIT = 20
MAX_CONCURRENCY = 2

FILLER_SOURCE_TYPES = frozenset({"rss", "api"})
FILLER_KEYS = frozenset({"grants-gov", "grants-gov-rss", "grants-gov-forecast"})
DENYLIST_KEYS = frozenset(
    {"minciencias", "heading_list", "wordpress", "bdn", "simpler-grants"}
)

CommitFn = Callable[[str, dict[str, Any]], None]
FetchFn = Callable[..., Awaitable[tuple[str, str, str]]]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Piloto full-capture (20-row dry-run default)")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    p.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Persist merge deltas (default: dry-run, no commit)",
    )
    return p.parse_args(argv)


def is_filler_source(source: Any) -> bool:
    key = getattr(source, "key", "") or ""
    source_type = (getattr(source, "source_type", "") or "").lower()
    if key in DENYLIST_KEYS:
        return False
    if source_type in FILLER_SOURCE_TYPES:
        return True
    if key in FILLER_KEYS:
        return True
    if source_type == "html":
        cfg = getattr(source, "connector_config", None)
        if cfg:
            return True
        # generic_html: html without denylist key and without specialized denylist
        return key not in DENYLIST_KEYS
    return False


def _gap_score(opp: Any) -> int:
    """Higher = more missing capture fields (prefer for piloto)."""
    score = 0
    if getattr(opp, "funding_amount_value", None) is None:
        score += 3
    if getattr(opp, "close_date", None) is None:
        score += 2
    if getattr(opp, "open_date", None) is None:
        score += 1
    if not getattr(opp, "application_url", None):
        score += 2
    for attr in (
        "eligible_applicants",
        "evaluation_criteria",
        "restrictions",
        "requirements",
        "documents_required",
    ):
        if not (getattr(opp, attr, None) or []):
            score += 1
    summary = getattr(opp, "summary", "") or ""
    try:
        from app.services.opportunity import is_thin_or_metadata_summary

        if is_thin_or_metadata_summary(summary):
            score += 2
    except Exception:
        if len(summary.strip()) < 80:
            score += 2
    return score


def select_piloto_rows(rows: Iterable[Any], limit: int = DEFAULT_LIMIT) -> list[Any]:
    eligible = [
        r
        for r in rows
        if isinstance(getattr(r, "official_url", None), str)
        and (getattr(r, "official_url") or "").strip()
    ]
    fillers = [r for r in eligible if is_filler_source(getattr(r, "source", None))]
    others = [r for r in eligible if r not in fillers]
    fillers.sort(key=_gap_score, reverse=True)
    others.sort(key=_gap_score, reverse=True)
    chosen = fillers[:limit]
    if len(chosen) < limit:
        chosen.extend(others[: limit - len(chosen)])
    return chosen[:limit]


def _prefer_longer_text(current: str, incoming: str) -> str:
    cur = (current or "").strip()
    inc = (incoming or "").strip()
    if not inc:
        return cur
    if not cur:
        return inc
    return inc if len(inc) > len(cur) else cur


def compute_merge_deltas(existing: Any, extracted: dict[str, Any]) -> dict[str, Any]:
    """IS-NULL / empty-list / longer-text merge shared by dry-run and execute."""
    deltas: dict[str, Any] = {}

    for key in (
        "open_date",
        "close_date",
        "funding_amount_value",
        "funding_amount_currency",
        "funding_amount_raw",
        "application_url",
    ):
        incoming = extracted.get(key)
        if incoming is None or incoming == "":
            continue
        current = getattr(existing, key, None)
        if current is None or current == "":
            deltas[key] = incoming

    for key in (
        "eligible_applicants",
        "evaluation_criteria",
        "restrictions",
        "requirements",
        "documents_required",
    ):
        incoming = extracted.get(key) or []
        if not incoming:
            continue
        current = getattr(existing, key, None) or []
        if not current:
            deltas[key] = list(incoming)

    for key in ("description", "raw_text"):
        incoming = extracted.get(key)
        if not isinstance(incoming, str) or not incoming.strip():
            continue
        current = getattr(existing, key, "") or ""
        chosen = _prefer_longer_text(current, incoming)
        if chosen and chosen != current:
            deltas[key] = chosen

    incoming_summary = extracted.get("summary")
    if isinstance(incoming_summary, str) and incoming_summary.strip():
        current_summary = getattr(existing, "summary", "") or ""
        try:
            from app.services.opportunity import is_thin_or_metadata_summary

            incoming_junk = is_thin_or_metadata_summary(incoming_summary)
            current_junk = is_thin_or_metadata_summary(current_summary)
        except Exception:
            incoming_junk = len(incoming_summary.strip()) < 80
            current_junk = len(current_summary.strip()) < 80
        if not incoming_junk and (current_junk or len(incoming_summary) > len(current_summary)):
            deltas["summary"] = incoming_summary.strip()

    return deltas


async def run_piloto(
    rows: Iterable[Any],
    *,
    limit: int = DEFAULT_LIMIT,
    execute: bool = False,
    fetch: FetchFn | None = None,
    commit_fn: CommitFn | None = None,
) -> dict[str, Any]:
    from app.connectors.common import extract_page_fields, fetch_httpx_text

    selected = select_piloto_rows(rows, limit=limit)
    fetch_fn = fetch or fetch_httpx_text
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    would_update = 0
    committed = 0

    async def _one(opp: Any) -> dict[str, Any] | None:
        nonlocal would_update, committed
        url = (getattr(opp, "official_url", None) or "").strip()
        if not url:
            return None
        async with sem:
            try:
                _final, html, _ctype = await fetch_fn(url)
            except Exception as exc:
                return {"id": getattr(opp, "id", None), "error": str(exc)}
        extracted = extract_page_fields(html=html, page_url=url)
        deltas = compute_merge_deltas(opp, extracted)
        if not deltas:
            return {"id": getattr(opp, "id", None), "deltas": {}}
        would_update += 1
        if execute and commit_fn is not None:
            commit_fn(str(getattr(opp, "id")), deltas)
            committed += 1
        return {"id": getattr(opp, "id", None), "deltas": deltas}

    results = await asyncio.gather(*[_one(r) for r in selected])
    return {
        "processed": len(selected),
        "would_update": would_update,
        "committed": committed,
        "dry_run": not execute,
        "results": [r for r in results if r is not None],
    }


def _load_rows_from_db() -> list[Any]:
    from app.db.session import SessionLocal
    from app.models import Opportunity, Source

    db = SessionLocal()
    try:
        opps = (
            db.query(Opportunity)
            .filter(Opportunity.official_url.isnot(None))
            .limit(500)
            .all()
        )
        source_ids = {o.source_id for o in opps if o.source_id}
        sources = {
            s.id: s
            for s in db.query(Source).filter(Source.id.in_(source_ids)).all()
        } if source_ids else {}
        for opp in opps:
            # Attach for select_piloto_rows / is_filler_source (no ORM relationship).
            opp.source = sources.get(opp.source_id)  # type: ignore[attr-defined]
        return opps
    finally:
        db.close()


def _commit_deltas(opp_id: str, deltas: dict[str, Any]) -> None:
    from app.db.session import SessionLocal
    from app.models import Opportunity

    db = SessionLocal()
    try:
        opp = db.query(Opportunity).filter(Opportunity.id == opp_id).one()
        for key, value in deltas.items():
            setattr(opp, key, value)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = _load_rows_from_db()
    report = asyncio.run(
        run_piloto(
            rows,
            limit=args.limit,
            execute=args.execute,
            commit_fn=_commit_deltas if args.execute else None,
        )
    )
    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(
        f"[{mode}] processed={report['processed']} "
        f"would_update={report['would_update']} committed={report['committed']}"
    )
    for item in report["results"]:
        deltas = item.get("deltas") or {}
        if item.get("error"):
            print(f"  {item.get('id')}: ERROR {item['error']}")
        elif deltas:
            print(f"  {item.get('id')}: fields={sorted(deltas.keys())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
