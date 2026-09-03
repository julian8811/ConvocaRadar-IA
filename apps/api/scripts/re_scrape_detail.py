#!/usr/bin/env python3
"""
re_scrape_detail — B2 stub: re-scrape detail pages with Playwright fallback.

Fixes B1 where enrich_candidates_batch (httpx-only) returned 0/5 funding for
grants.gov because the detail page is an SPA shell (200 with no h1 / <15k body)
and the common fetch only falls back to Playwright on 4xx/5xx.

Heuristic: when httpx result is empty/thin and --force-playwright or
source == grants-gov, retry via render_page_html(wait_selector='h1') and
manual parse (funding via $ regex + extract_dates).

Usage:
  DATABASE_URL=... python apps/api/scripts/re_scrape_detail.py --source grants-gov --limit 2 --dry-run --force-playwright --verbose
  DATABASE_URL=... python apps/api/scripts/re_scrape_detail.py --source icetex-vigentes --limit 5 --dry-run --verbose
  DATABASE_URL=... python apps/api/scripts/re_scrape_detail.py --source grants-gov --limit 10 --execute --force-playwright
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

# Ensure app is importable when run as file
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.connectors.base import OpportunityCandidate
from app.connectors.common import (
    enrich_candidates_batch,
    enrich_from_detail_page,
    extract_dates,
    extract_funding_amount,
    render_page_html,
)
from app.services.opportunity import _parse_funding_amount

FUNDING_DOLLAR_RE = re.compile(r"\$\s*[\d,\.]+")


def get_session():
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        engine = create_engine(
            db_url, connect_args={"prepare_threshold": None} if db_url.startswith("postgresql") else {}
        )
        maker = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        return maker()
    from app.db.session import SessionLocal

    return SessionLocal()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Re-scrape opportunity detail pages with PW fallback (B2 stub)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--source", required=True, help="Source key (e.g. grants-gov, icetex-vigentes, findeter-convocatorias, novo-nordisk-grants)")
    p.add_argument("--limit", type=int, default=5, help="Max opportunities to process")
    p.add_argument("--dry-run", action="store_true", default=True, help="Dry-run only (no DB writes) — default true")
    p.add_argument("--no-dry-run", dest="dry_run", action="store_false", help="Disable dry-run")
    p.add_argument("--execute", action="store_true", help="Commit updates to DB (requires --no-dry-run or explicit)")
    p.add_argument("--force-playwright", action="store_true", default=False, help="Force Playwright retry when httpx result is thin/empty")
    p.add_argument("--verbose", action="store_true", help="Verbose logging")
    return p.parse_args()


async def enrich_one(url: str, title_hint: str, summary: str, raw_text: str, verbose: bool) -> dict | None:
    cand = OpportunityCandidate(title=title_hint or "re_scrape stub", entity="re_scrape", country="Por validar", official_url=url, summary=summary or "", raw_text=raw_text or "", confidence_score=0.55)
    try:
        enriched = await enrich_candidates_batch([cand])
        if enriched:
            c = enriched[0]
            if c.title and c.title != cand.title or c.funding_amount_raw or c.close_date:
                out: dict = {}
                if c.title: out["title"] = c.title
                if c.summary: out["summary"] = c.summary
                if c.funding_amount_raw: out["funding_amount_raw"] = c.funding_amount_raw
                if c.close_date: out["close_date"] = c.close_date
                if c.open_date: out["open_date"] = c.open_date
                return out if out.get("title") else None
        return await enrich_from_detail_page(url)
    except Exception as e:
        if verbose: print(f"  [enrich_one] failed {url}: {e}")
        return None


async def playwright_retry(url: str, verbose: bool) -> dict | None:
    try:
        final_url, html, ctype = await render_page_html(url, wait_selector="h1", wait_selector_timeout_ms=8000)
        if verbose: print(f"  [pw] rendered {url} -> len={len(html)} ct={ctype}")
    except Exception as e:
        if verbose: print(f"  [pw] render failed {url}: {e}")
        return None
    if len(html) < 500:
        if verbose: print(f"  [pw] html too short ({len(html)})")
        return None
    try:
        from selectolax.parser import HTMLParser
        tree = HTMLParser(html)
        h1 = tree.css_first("h1")
        title = h1.text().strip() if h1 and h1.text() else None
        body = tree.css_first("body")
        body_text = (body.text().strip() if body else html)[:8000]
    except Exception:
        h1_m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
        title = re.sub(r"<[^>]+>", "", h1_m.group(1)).strip() if h1_m else None
        body_text = re.sub(r"<[^>]+>", " ", html)
    body_text = re.sub(r"\s+", " ", body_text).strip()
    result: dict = {}
    if title: result["title"] = title[:180]
    funding_raw = extract_funding_amount(body_text) or (FUNDING_DOLLAR_RE.search(body_text).group(0).strip() if FUNDING_DOLLAR_RE.search(body_text) else None)
    # Filter false positive: "Funding Adjustment 3" type strings (no $/currency, tiny number)
    if funding_raw and re.search(r"Adjustment\s+\d", funding_raw, re.I):
        funding_raw = None
    # Require $ or explicit currency for funding_raw; reject bare small numbers
    if funding_raw and "$" not in funding_raw and not re.search(r"(?:USD|COP|EUR|BRL|GBP)", funding_raw, re.I):
        funding_raw = None
    if funding_raw: result["funding_amount_raw"] = funding_raw[:500]
    od, cd = extract_dates(body_text[:4000])
    if cd: result["close_date"] = cd
    if od: result["open_date"] = od
    if verbose and title: print(f"  [pw] title='{title[:80]}' funding='{funding_raw}' close={cd}")
    return result if result.get("title") else None


async def process_source(args: argparse.Namespace):
    dry_run = False if args.execute else args.dry_run

    db = get_session()
    try:
        # Resolve source
        row = db.execute(text("SELECT id, key, base_url FROM sources WHERE key=:k"), {"k": args.source}).fetchone()
        if not row:
            print(f"[error] source key not found: {args.source}")
            sys.exit(1)
        source_id, source_key, base_url = row[0], row[1], row[2]
        print(f"=== re_scrape_detail B2 stub ===")
        print(f" source={source_key} id={source_id[:8]} base_url={base_url}")
        print(f" limit={args.limit} dry_run={dry_run} execute={args.execute} force_pw={args.force_playwright} verbose={args.verbose}")
        print(f" DB: {os.environ.get('DATABASE_URL', '(settings.database_url)')[:70]}...")

        if dry_run:
            q = text("SELECT id, official_url, title, summary, raw_text, funding_amount_value, close_date, open_date, funding_amount_raw FROM opportunities WHERE source_id=:sid AND official_url IS NOT NULL ORDER BY created_at DESC LIMIT :lim")
        else:
            q = text("SELECT id, official_url, title, summary, raw_text, funding_amount_value, close_date, open_date, funding_amount_raw FROM opportunities WHERE source_id=:sid AND official_url IS NOT NULL AND funding_amount_value IS NULL ORDER BY created_at DESC LIMIT :lim")
        rows = db.execute(q, {"sid": source_id, "lim": args.limit}).fetchall()
        print(f" fetched {len(rows)} opportunities (query={'dry-run all' if dry_run else 'execute IS NULL'})")
        if not rows:
            if args.source == "icetex-vigentes":
                print(" icetex has 0 official_url - needs connector fix (no detail pages to re-scrape)")
            # try fallback info
            total = db.execute(text("SELECT count(*) FROM opportunities WHERE source_id=:sid"), {"sid": source_id}).scalar()
            with_url = db.execute(text("SELECT count(*) FROM opportunities WHERE source_id=:sid AND official_url IS NOT NULL"), {"sid": source_id}).scalar()
            print(f"  source total={total} with_url={with_url}")
            return

        # header for dry-run table
        if dry_run:
            print()
            print(f"{'URL':55} | {'funding_raw':20} | {'close':12} | {'title':30} | would_update")
            print("-" * 150)

        should_pw_global = args.force_playwright or args.source == "grants-gov"
        updated = 0
        would_update = 0

        for r in rows:
            oid, url, title, summary, raw_text, fund_val, close_dt, open_dt, fund_raw = r
            if args.verbose:
                print(f"\n[opp] {oid[:8]} url={url}")
                print(f"  title='{ (title or '')[:80]}' fund_val={fund_val} close={close_dt} raw_len={len(raw_text or '')}")

            data = await enrich_one(url, title or "", summary or "", raw_text or "", args.verbose)

            # Heuristic PW retry
            need_pw = False
            if data is None:
                need_pw = True
            elif not data.get("title"):
                need_pw = True
            elif not data.get("funding_amount_raw"):
                # thin funding -> retry if grants-gov or forced
                need_pw = True
            # also check body thin via raw_text length hint
            if need_pw and should_pw_global:
                if args.verbose:
                    reason = "None" if data is None else ("no title" if not data.get("title") else "no funding")
                    print(f"  [heuristic] httpx thin ({reason}) -> PW retry (force={args.force_playwright} source={args.source})")
                pw_data = await playwright_retry(url, args.verbose)
                if pw_data:
                    # merge: pw overrides only missing
                    if data is None:
                        data = pw_data
                    else:
                        for k, v in pw_data.items():
                            if k not in data or not data[k]:
                                data[k] = v
                elif args.verbose:
                    print(f"  [heuristic] PW retry returned None for {url}")

            # derive funding_raw/close for display or commit
            funding_raw_out = (data.get("funding_amount_raw") if data else None) or ""
            close_out = data.get("close_date") if data and data.get("close_date") else None
            title_out = (data.get("title") if data else None) or title or ""

            would = False
            if fund_val is None and funding_raw_out:
                would = True
            elif close_dt is None and close_out is not None:
                would = True

            if dry_run:
                fw = funding_raw_out[:20] if funding_raw_out else "-"
                cl = close_out.isoformat()[:10] if close_out else (close_dt.isoformat()[:10] if close_dt else "-")
                print(f"{url[:55]:55} | {fw:20} | {cl:12} | {title_out[:30]:30} | {would}")

            else:
                # execute: IS NULL guard writes only
                if data is None:
                    continue
                # funding guard
                if fund_val is None and data.get("funding_amount_raw"):
                    raw = data["funding_amount_raw"]
                    # Filter false positive Adjustment N before parse (B2 fix)
                    if raw and re.search(r"Adjustment\s+\d", raw, re.I):
                        if args.verbose:
                            print(f"  [filter] reject Adjustment false positive '{raw[:40]}'")
                        raw = None
                    if raw:
                        # re-resolve country/url for _parse_funding_amount
                        # infer via source key is fine; use base_url
                        val, cur = _parse_funding_amount(raw, country=None, url=url)
                        if val is not None and cur is not None:
                            db.execute(
                                text("UPDATE opportunities SET funding_amount_raw=:raw, funding_amount_value=:val, funding_amount_currency=:cur WHERE id=:oid AND funding_amount_value IS NULL"),
                                {"raw": raw[:1000], "val": val, "cur": cur, "oid": oid},
                            )
                            would_update += 1
                            updated += 1
                            if args.verbose:
                                print(f"  [write] funding {raw[:40]} -> {val} {cur}")
                # close/open guard
                if close_dt is None and data.get("close_date") is not None:
                    cd = data["close_date"]
                    od = data.get("open_date")
                    if od and open_dt is None:
                        db.execute(text("UPDATE opportunities SET close_date=:cd, open_date=:od WHERE id=:oid AND close_date IS NULL"), {"cd": cd, "od": od, "oid": oid})
                    else:
                        db.execute(text("UPDATE opportunities SET close_date=:cd WHERE id=:oid AND close_date IS NULL"), {"cd": cd, "oid": oid})
                    if args.verbose:
                        print(f"  [write] close {cd} open={od}")

                if updated % 10 == 0 and updated > 0:
                    db.commit()
                    if args.verbose:
                        print(f"  [commit] batch 10 ({updated})")

        if dry_run:
            print()
            print(f" dry-run done: {len(rows)} checked (no writes, idempotent)")
        else:
            db.commit()
            print(f" execute done: {updated} funding/close updates committed (would_update check={would_update})")

    finally:
        db.close()


def main():
    args = parse_args()
    # normalize: --execute implies no dry-run
    asyncio.run(process_source(args))


if __name__ == "__main__":
    main()
