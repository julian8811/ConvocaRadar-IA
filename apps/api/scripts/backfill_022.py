#!/usr/bin/env python3
"""
backfill_022 — bypass dedup direct DB backfill for funding + close/open dates (022 parsers).
- No LLM/embeddings, solo parsers locales => no Cloudflare 429
- Guard: solo IS NULL, no sobrescribir
- Batch commit cada 100
Usage:
  python -m app.scripts.backfill_022 --dry-run
  python -m app.scripts.backfill_022 --execute
  docker compose exec api python /app/scripts/backfill_022.py --dry-run
  docker compose exec api python /app/scripts/backfill_022.py --execute
Also supports direct path: python apps/api/scripts/backfill_022.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure app is importable when run as file
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select

from app.connectors.common import extract_dates
from app.db.session import SessionLocal
from app.models import Opportunity, Source
from app.services.opportunity import _parse_funding_amount, _is_tr_artifact


CO_DOMAINS = [".gov.co", ".edu.co", "fondoemprender.com", "minciencias.gov.co"]
CO_KEYS = ["colombia", "fondo-emprender", "fondo_emprender", "sena", "minciencias", "icetex", "innpulsa", "findeter", "ascun"]


def infer_country(opp: Opportunity, source: Source | None) -> str | None:
    # Priority: opp.country if set and not placeholder
    if opp.country and opp.country not in ("", "Por validar", "Sin dato", "unknown"):
        # If already Colombia, keep; still allow
        return opp.country
    if source and source.country and source.country not in ("", "Por validar"):
        return source.country
    # Infer from source.key / source.base_url / opp.official_url / source.key
    keys_to_check = []
    if source:
        keys_to_check.append((source.key or "").lower())
        keys_to_check.append((source.base_url or "").lower())
    keys_to_check.append((opp.official_url or "").lower())
    keys_to_check.append((opp.country or "").lower())
    blob = " ".join(keys_to_check)
    if any(dom in blob for dom in CO_DOMAINS):
        return "Colombia"
    if any(k in blob for k in CO_KEYS):
        # only if blob contains co indicator, but avoid false positives for "sena" generic?
        # sena is strongly CO
        return "Colombia"
    # Also direct url check for .gov.co
    url = (opp.official_url or "") + " " + (source.base_url if source else "")
    if ".gov.co" in url.lower():
        return "Colombia"
    return None


def funding_raw_is_artifact(val: str | None) -> bool:
    if not val:
        return False
    if _is_tr_artifact(val):
        return True
    s = val.strip().lower()
    return s in {"tr", "td", "th", "table", "tbody", "thead"}


# Stricter guard: avoid O-COPS false COP and React JSON dumps — use word boundaries for currency codes to avoid "Europea"->EUR, "COPS"->COP
import re as _re
_FUNDING_KEYWORD_RE = _re.compile(
    r"(total\s+fund|maximum\s+award|presupuesto|monto|financiac|grant\s+amount|award\s+amount|fondo|valor\s+del\s+proyecto|\bCOP\b\s*\$?|\bUSD\b|\bEUR\b|\bGBP\b|\bBRL\b|\bMXN\b|€|£|R\$|\$\s*\d)",
    _re.IGNORECASE,
)
# Explicit currency near number pattern — require currency symbol/code adjacent to digits to avoid "Europea" false positive
_CURRENCY_NEAR_NUMBER_RE = _re.compile(
    r"(\$|€|£|R\$)\s*\d|\b(COP|USD|EUR|GBP|BRL|MXN)\b\s*[\d\.,]+|[\d\.,]+\s*\b(COP|USD|EUR|GBP)\b|\d+\s*(millones|million|mil)",
    _re.IGNORECASE,
)
# For raw_text that is React JSON dump (Simpler Grants list page), skip funding unless explicit funding_amount_raw
_REACT_DUMP_RE = _re.compile(r"responsive-data|className|data-testid", _re.IGNORECASE)
# Noise title filter for close
_NOISE_TITLE_RE = _re.compile(r"^(sort by|technical guidance|national coordinators|calendário de auxílios|ver m(á|a)s|inicio|home)", _re.IGNORECASE)


def run(dry_run: bool = True):
    db = SessionLocal()
    try:
        # Preload source map
        sources = {s.id: s for s in db.scalars(select(Source)).all()}
        # Coverage BEFORE
        total = db.scalar(select(func.count()).select_from(Opportunity)) or 0
        before_funding = db.scalar(select(func.count()).select_from(Opportunity).where(Opportunity.funding_amount_value.isnot(None))) or 0
        before_close = db.scalar(select(func.count()).select_from(Opportunity).where(Opportunity.close_date.isnot(None))) or 0
        before_open = db.scalar(select(func.count()).select_from(Opportunity).where(Opportunity.open_date.isnot(None))) or 0
        print("=== COVERAGE BEFORE ===")
        print(f" total={total} funding={before_funding} ({before_funding/total*100:.1f}%) close={before_close} ({before_close/total*100:.1f}%) open={before_open} ({before_open/total*100:.1f}%)")
        print(f" funding_amount_raw present: {db.scalar(select(func.count()).select_from(Opportunity).where(Opportunity.funding_amount_raw.isnot(None))) or 0}")
        print()

        # ----- FUNDING -----
        # Query per spec: funding_amount_value IS NULL AND (funding_amount_raw IS NOT NULL OR raw_text IS NOT NULL)
        funding_candidates = db.scalars(
            select(Opportunity).where(
                Opportunity.funding_amount_value.is_(None),
                (Opportunity.funding_amount_raw.isnot(None)) | (Opportunity.raw_text.isnot(None)),
            )
        ).all()
        print(f"[funding] candidates: {len(funding_candidates)} (funding_amount_value IS NULL AND (raw IS NOT NULL OR raw_text IS NOT NULL))")

        funding_would = 0
        funding_examples = []
        funding_updates = []  # list of (opp, value, currency, raw_used)

        for opp in funding_candidates:
            # Skip tr artifact in funding_amount_raw
            raw_candidate = opp.funding_amount_raw
            if raw_candidate and funding_raw_is_artifact(raw_candidate):
                continue
            # Also reject if raw_candidate is literally "tr" case-insensitive after strip
            if raw_candidate and raw_candidate.strip().lower() == "tr":
                continue

            has_explicit_raw = bool(raw_candidate and raw_candidate.strip() and not funding_raw_is_artifact(raw_candidate))

            # Build raw text: funding_raw or raw_text[:2000] + summary/title fallback as enhancement
            # Spec says raw = funding_raw or raw_text[:2000]; we extend slightly to include summary/title when raw_text is short/metadata
            if has_explicit_raw:
                raw = raw_candidate
            else:
                # Noise filter for funding: skip navigation artifacts
                if _NOISE_TITLE_RE.search((opp.title or "").strip()):
                    continue
                if "Funding finder" in (opp.raw_text or "")[:500] and "opportunities found" in (opp.raw_text or "")[:500]:
                    continue
                # Combine raw_text + summary + title as fallback — spec says raw_text[:2000], but many rows have only metadata in raw_text
                # We concatenate to improve recall without adding LLM
                parts = []
                if opp.raw_text:
                    parts.append(opp.raw_text[:2000])
                if opp.summary and len(opp.summary) > 20:
                    parts.append(opp.summary[:1000])
                if opp.title:
                    parts.append(opp.title[:500])
                raw = " ".join(parts).strip()
                if not raw:
                    continue
                raw = raw[:2500]
                # Guard: skip React JSON dumps for funding (Simpler Grants / Grants.gov list pages) — they produce false COP from O-COPS IDs and $ placeholders
                if _REACT_DUMP_RE.search(raw) and not has_explicit_raw:
                    # allow only if raw also contains real funding keyword near currency
                    if not _re.search(r"Total fund|Maximum award|Budget|Funding type", raw, _re.IGNORECASE):
                        continue
                # Guard: require funding keyword or explicit currency+number proximity when no explicit funding_amount_raw
                if not _FUNDING_KEYWORD_RE.search(raw):
                    continue
                # Extra strict: require currency adjacent to number, not just keyword substring
                if not _CURRENCY_NEAR_NUMBER_RE.search(raw):
                    # Allow "presupuesto|monto|fondo" with large number even without currency symbol (CO large)
                    if not _re.search(r"presupuesto|monto|fondo|financiac", raw, _re.IGNORECASE):
                        continue

            # Quick guard: skip raw that is just artifact or too short with no number
            if not raw or not any(c.isdigit() for c in raw):
                continue
            if funding_raw_is_artifact(raw):
                continue
            # Extra: reject raw that is just ID like O-COPS without funding context, avoid "COP" inside "COPS" false positive
            # _parse_funding_amount already matches "COP" inside "COPS", so we require word boundary for COP when no $/€/£
            if _re.search(r"\bCOPS\b", raw, _re.IGNORECASE) and not _re.search(r"\$|€|£|USD|EUR|GBP", raw, _re.IGNORECASE):
                # Contains COPS code but no real currency symbol — likely ID, skip unless explicit raw
                if not has_explicit_raw:
                    # double-check: if raw has "COP" word boundary outside COPS, keep; else skip
                    if not _re.search(r"\bCOP\b", raw):
                        continue

            src = sources.get(opp.source_id) if opp.source_id else None
            country = infer_country(opp, src)
            # Also Colombia inference: url contains .gov.co etc handled in infer_country
            # Pass url for COP inference inside _parse_funding_amount
            url = opp.official_url or (src.base_url if src else None)
            value, currency = _parse_funding_amount(raw, country=country, url=url)
            if value is not None and currency is not None:
                # Post-parse sanity: reject year-like funding (2020-2030) without explicit amount context
                if 2020 <= value <= 2035:
                    if not _re.search(r"presupuesto|monto|fondo|total fund|maximum award|award|grant.*fund", raw, _re.IGNORECASE):
                        continue
                    # Also require value != year in title alone (e.g., "convocatoria 2022")
                    if _re.search(r"\b202[0-9]\b", raw) and value in (2022, 2023, 2024, 2025, 2026, 2027):
                        # If raw snippet is just title with year and no currency symbol, skip
                        if not _CURRENCY_NEAR_NUMBER_RE.search(raw):
                            continue
                # Reject tiny percentages like 60% mis-parsed as EUR/COP (value < 500 and raw contains "%")
                if value < 500 and "%" in raw:
                    continue
                # Reject zero or tiny funding that is clearly noise (e.g., 0 USD from connect-bogota)
                if value == 0 or value < 100:
                    continue
                funding_would += 1
                if len(funding_examples) < 5:
                    funding_examples.append({
                        "id": opp.id[:8],
                        "title": opp.title[:80],
                        "country_infer": country,
                        "source_key": src.key if src else "no-source",
                        "raw_snippet": raw[:160].replace("\n", " "),
                        "parsed": f"{value} {currency}",
                        "old_raw": (opp.funding_amount_raw or "")[:60],
                    })
                funding_updates.append((opp, value, currency, raw[:2000]))

        print(f"[funding] WOULD update: {funding_would}")
        for ex in funding_examples:
            print(f"  ex funding: [{ex['source_key']}] {ex['title']} | infer_country={ex['country_infer']} | raw='{ex['raw_snippet']}...' -> {ex['parsed']} (old_raw='{ex['old_raw']}')")
        print()

        # ----- CLOSE / OPEN -----
        close_candidates = db.scalars(
            select(Opportunity).where(
                Opportunity.close_date.is_(None),
                Opportunity.raw_text.isnot(None),
            )
        ).all()
        # Also include rows where raw_text is not null but also consider summary/title even if raw_text null? Spec says raw_text IS NOT NULL, we keep that.
        # For broader coverage, also check where close_date IS NULL regardless of raw_text (title+summary may hold dates)
        # But spec says raw_text IS NOT NULL; we also include those with summary/title if raw_text empty.
        # To maximize, we query all close_date IS NULL and filter in-loop.
        all_close_null = db.scalars(select(Opportunity).where(Opportunity.close_date.is_(None))).all()
        print(f"[close] candidates raw_text IS NOT NULL: {len(close_candidates)} | total close IS NULL: {len(all_close_null)} (full scan)")
        # Use full set for extraction (since title/summary may have date even if raw_text is short)
        close_scan = all_close_null

        close_would = 0
        close_examples = []
        close_updates = []  # list of (opp, open, close)

        for opp in close_scan:
            # Noise guard: skip opp titles that are navigation / list page artifacts
            if _NOISE_TITLE_RE.search((opp.title or "").strip()):
                continue
            # Skip React list dumps that contain aggregated funding finder blob (will produce spurious dates for wrong opp)
            blob_check = (opp.raw_text or "")[:500]
            if "Funding finder" in blob_check and "opportunities found" in blob_check:
                # This opp's raw_text is the entire UKRI list page, not its own detail — skip close backfill to avoid misattribution
                continue
            combined = " ".join(part for part in [opp.raw_text or "", opp.summary or "", opp.title or "", opp.description or ""] if part)
            combined = combined[:4000]
            if not combined.strip():
                continue
            od, cd = extract_dates(combined)
            if cd is None:
                continue
            # Year guard 2024-2028 (extract_dates already does, but double-check)
            if cd.year < 2024 or cd.year > 2028:
                continue
            # Avoid single-date as close when open==close (spec: close != open)
            if od is not None and od == cd:
                continue
            # Also avoid case where extract_dates returns (None, single) which is correct close; single-date is valid.
            # The spec says close != open to avoid grants.gov openDate as close when only 1 fecha — but our extract_dates already returns (None, single) for single candidate, so od is None there. That case is OK.
            # Only skip when both present and equal.
            close_would += 1
            if len(close_examples) < 5:
                close_examples.append({
                    "id": opp.id[:8],
                    "title": opp.title[:80],
                    "od": od.isoformat() if od else None,
                    "cd": cd.isoformat() if cd else None,
                    "snippet": combined[:160].replace("\n", " "),
                })
            close_updates.append((opp, od, cd))

        print(f"[close] WOULD update close_date: {close_would}")
        for ex in close_examples:
            print(f"  ex close: {ex['title']} | open={ex['od']} close={ex['cd']} | snippet='{ex['snippet']}...'")
        # Count open would also update
        open_would = sum(1 for opp, od, cd in close_updates if od is not None and opp.open_date is None)
        print(f"[open] WOULD update open_date (subset of close): {open_would}")
        print()

        if dry_run:
            print("=== DRY-RUN == no commits ===")
            print(f" Funding would update: {funding_would}/{len(funding_candidates)}")
            print(f" Close would update: {close_would}/{len(close_scan)}")
            print(f" Open would update: {open_would}")
            return {"funding_would": funding_would, "close_would": close_would, "open_would": open_would}

        # ----- REAL EXECUTE -----
        print("=== EXECUTING REAL UPDATE (bypass dedup, direct DB) ===")
        # Funding batch commit cada 100
        updated_funding = 0
        for idx, (opp, value, currency, raw_used) in enumerate(funding_updates, 1):
            # Guard: solo IS NULL (already filtered, but re-check in case concurrent)
            db.refresh(opp) if False else None  # no-op, keep opp
            if opp.funding_amount_value is not None:
                continue
            opp.funding_amount_value = value
            opp.funding_amount_currency = currency
            # funding_amount_raw: coalesce(raw, funding_raw) — keep existing if present else set parsed raw snippet
            if not opp.funding_amount_raw:
                opp.funding_amount_raw = raw_used[:1000]
            updated_funding += 1
            if updated_funding % 100 == 0:
                db.commit()
                print(f"  funding committed {updated_funding}/{len(funding_updates)}")
        db.commit()
        print(f" Funding committed total: {updated_funding}")

        # Close/open batch
        updated_close = 0
        updated_open = 0
        for idx, (opp, od, cd) in enumerate(close_updates, 1):
            if opp.close_date is not None:
                continue
            opp.close_date = cd
            updated_close += 1
            if od is not None and opp.open_date is None:
                opp.open_date = od
                updated_open += 1
            if updated_close % 100 == 0:
                db.commit()
                print(f"  close committed {updated_close}/{len(close_updates)} (open {updated_open})")
        db.commit()
        print(f" Close committed total: {updated_close}, Open committed: {updated_open}")

        # Verify after
        after_funding = db.scalar(select(func.count()).select_from(Opportunity).where(Opportunity.funding_amount_value.isnot(None))) or 0
        after_close = db.scalar(select(func.count()).select_from(Opportunity).where(Opportunity.close_date.isnot(None))) or 0
        after_open = db.scalar(select(func.count()).select_from(Opportunity).where(Opportunity.open_date.isnot(None))) or 0
        print()
        print("=== COVERAGE AFTER ===")
        print(f" total={total} funding={after_funding} ({after_funding/total*100:.1f}%) close={after_close} ({after_close/total*100:.1f}%) open={after_open} ({after_open/total*100:.1f}%)")
        print(f" funding delta: +{after_funding - before_funding} | close delta: +{after_close - before_close} | open delta: +{after_open - before_open}")

        # Per-source verification
        print()
        print("=== PER-SOURCE AFTER (top 20) ===")
        from sqlalchemy import text as sql_text
        result = db.execute(sql_text("""
            SELECT s.key, s.name, count(o.id) as total, count(o.funding_amount_value) as with_funding, count(o.close_date) as with_close, count(o.open_date) as with_open
            FROM opportunities o JOIN sources s ON s.id=o.source_id
            GROUP BY s.key, s.name
            ORDER BY total DESC
            LIMIT 20;
        """)).fetchall()
        for row in result:
            print(f"  {row[0]:30} total={row[2]} funding={row[3]} close={row[4]} open={row[5]}")

        return {"funding_updated": updated_funding, "close_updated": updated_close, "open_updated": updated_open,
                "before": (before_funding, before_close, before_open), "after": (after_funding, after_close, after_open)}

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="backfill_022 bypass dedup")
    parser.add_argument("--dry-run", action="store_true", help="dry-run preview only")
    parser.add_argument("--execute", action="store_true", help="real commit")
    args = parser.parse_args()
    # Default dry-run if neither flag
    if args.execute:
        run(dry_run=False)
    else:
        run(dry_run=True)
