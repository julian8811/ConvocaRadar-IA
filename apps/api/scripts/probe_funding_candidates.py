#!/usr/bin/env python3
"""
probe_funding_candidates — audit the 1821 funding discards (option A).

Replicates *exactly* the guards from backfill_022.py to classify *why* each
candidate row (funding_amount_value IS NULL AND (funding_amount_raw IS NOT NULL OR raw_text IS NOT NULL))
was discarded, and whether it would actually parse via _parse_funding_amount.

Usage:
  DATABASE_URL=postgresql+psycopg://convocaradar:...@localhost:5434/convocaradar python apps/api/scripts/probe_funding_candidates.py
  DATABASE_URL=... python apps/api/scripts/probe_funding_candidates.py --limit 100
  python apps/api/scripts/probe_funding_candidates.py --help
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Ensure app is importable when run as file
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import Opportunity, Source
from app.services.opportunity import _is_tr_artifact, _parse_funding_amount

# ---------------------------------------------------------------------------
# Regexes + helpers — exact copies from backfill_022.py (do not drift)
# ---------------------------------------------------------------------------
CO_DOMAINS = [".gov.co", ".edu.co", "fondoemprender.com", "minciencias.gov.co"]
CO_KEYS = ["colombia", "fondo-emprender", "fondo_emprender", "sena", "minciencias", "icetex", "innpulsa", "findeter", "ascun"]

_FUNDING_KEYWORD_RE = re.compile(
    r"(total\s+fund|maximum\s+award|presupuesto|monto|financiac|grant\s+amount|award\s+amount|fondo|valor\s+del\s+proyecto|\bCOP\b\s*\$?|\bUSD\b|\bEUR\b|\bGBP\b|\bBRL\b|\bMXN\b|€|£|R\$|\$\s*\d)",
    re.IGNORECASE,
)
_CURRENCY_NEAR_NUMBER_RE = re.compile(
    r"(\$|€|£|R\$)\s*\d|\b(COP|USD|EUR|GBP|BRL|MXN)\b\s*[\d\.,]+|[\d\.,]+\s*\b(COP|USD|EUR|GBP)\b|\d+\s*(millones|million|mil)",
    re.IGNORECASE,
)
_REACT_DUMP_RE = re.compile(r"responsive-data|className|data-testid", re.IGNORECASE)
_NOISE_TITLE_RE = re.compile(r"^(sort by|technical guidance|national coordinators|calendário de auxílios|ver m(á|a)s|inicio|home)", re.IGNORECASE)


def infer_country(opp: Opportunity, source: Source | None) -> str | None:
    if opp.country and opp.country not in ("", "Por validar", "Sin dato", "unknown"):
        return opp.country
    if source and source.country and source.country not in ("", "Por validar"):
        return source.country
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
        return "Colombia"
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


def get_session():
    """Return a Session, honoring DATABASE_URL env override for probe runs."""
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        # Normalize: backfill uses postgresql+psycopg, plain postgresql also works
        engine = create_engine(db_url, connect_args={"prepare_threshold": None} if db_url.startswith("postgresql") else {})
        maker = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        return maker()
    # Fallback to app default SessionLocal (reads settings.database_url)
    from app.db.session import SessionLocal  # lazy import after sys.path

    return SessionLocal()


def classify_one(opp: Opportunity, source: Source | None) -> tuple[str, str | None, str | None, str | None]:
    """
    Replicate backfill_022 guards in exact order.
    Returns (reason, raw_used_or_none, parsed_value_currency_or_none, country_infer).
    reason is first discard reason, or WOULD_PARSE if it passes all guards and parses.
    Also returns raw snippet for sampling.
    """
    raw_candidate = opp.funding_amount_raw

    # --- artifact guard on funding_amount_raw ---
    if raw_candidate and funding_raw_is_artifact(raw_candidate):
        return "artifact_raw", None, None, None
    if raw_candidate and raw_candidate.strip().lower() == "tr":
        return "artifact_raw", None, None, None

    has_explicit_raw = bool(raw_candidate and raw_candidate.strip() and not funding_raw_is_artifact(raw_candidate))

    raw: str | None = None

    if has_explicit_raw:
        raw = raw_candidate
    else:
        # noise title
        if _NOISE_TITLE_RE.search((opp.title or "").strip()):
            return "noise_title", None, None, None
        # funding finder blob (UKRI list page)
        blob_check = (opp.raw_text or "")[:500]
        if "Funding finder" in blob_check and "opportunities found" in blob_check:
            return "funding_finder_blob", None, None, None

        parts: list[str] = []
        if opp.raw_text:
            parts.append(opp.raw_text[:2000])
        if opp.summary and len(opp.summary) > 20:
            parts.append(opp.summary[:1000])
        if opp.title:
            parts.append(opp.title[:500])
        raw = " ".join(parts).strip()
        if not raw:
            return "empty_raw", None, None, None
        raw = raw[:2500]

        if _REACT_DUMP_RE.search(raw) and not has_explicit_raw:
            if not re.search(r"Total fund|Maximum award|Budget|Funding type", raw, re.IGNORECASE):
                return "react_dump_no_keyword", raw, None, None

        if not _FUNDING_KEYWORD_RE.search(raw):
            return "no_funding_keyword", raw, None, None

        if not _CURRENCY_NEAR_NUMBER_RE.search(raw):
            if not re.search(r"presupuesto|monto|fondo|financiac", raw, re.IGNORECASE):
                return "no_currency_near_number", raw, None, None
            # else allowed via presupuesto/monto/fondo bypass — fall through

    # raw is now set (either explicit or constructed)
    assert raw is not None

    if not raw or not any(c.isdigit() for c in raw):
        return "no_digit", raw, None, None

    if funding_raw_is_artifact(raw):
        return "artifact_raw_post", raw, None, None

    if re.search(r"\bCOPS\b", raw, re.IGNORECASE) and not re.search(r"\$|€|£|USD|EUR|GBP", raw, re.IGNORECASE):
        if not has_explicit_raw:
            if not re.search(r"\bCOP\b", raw):
                return "cops_false_positive", raw, None, None

    country = infer_country(opp, source)
    url = opp.official_url or (source.base_url if source else None)
    value, currency = _parse_funding_amount(raw, country=country, url=url)

    if value is None and currency is None:
        return "parse_none", raw, None, country

    # post-parse sanity (exact copy from backfill_022)
    if value is not None and 2020 <= value <= 2035:
        if not re.search(r"presupuesto|monto|fondo|total fund|maximum award|award|grant.*fund", raw, re.IGNORECASE):
            return "year_sanity", raw, f"{value} {currency}", country
        if re.search(r"\b202[0-9]\b", raw) and value in (2022, 2023, 2024, 2025, 2026, 2027):
            if not _CURRENCY_NEAR_NUMBER_RE.search(raw):
                return "year_sanity", raw, f"{value} {currency}", country

    if value is not None and value < 500 and "%" in raw:
        return "percent_small", raw, f"{value} {currency}", country

    if value is not None and (value == 0 or value < 100):
        return "tiny_value", raw, f"{value} {currency}", country

    if value is not None and currency is not None:
        return "WOULD_PARSE", raw, f"{value} {currency}", country

    # Fallback — should not happen but classify as parse_none
    return "parse_none", raw, None, country


def main():
    parser = argparse.ArgumentParser(description="Probe funding candidates — audit 1821 discards (option A)")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of candidates to evaluate (for quick checks)")
    args = parser.parse_args()

    db = get_session()
    try:
        sources = {s.id: s for s in db.scalars(select(Source)).all()}

        q = select(Opportunity).where(
            Opportunity.funding_amount_value.is_(None),
            (Opportunity.funding_amount_raw.isnot(None)) | (Opportunity.raw_text.isnot(None)),
        )
        candidates = db.scalars(q).all()
        total = len(candidates)
        print("=== PROBE FUNDING CANDIDATES (option A) ===")
        print(f" DB: {os.environ.get('DATABASE_URL', '(default settings.database_url)')[:60]}...")
        print(f" Total candidates (funding_amount_value IS NULL AND (raw IS NOT NULL OR raw_text IS NOT NULL)): {total}")
        if args.limit:
            print(f" --limit {args.limit} applied: evaluating first {min(args.limit, total)} rows")
            candidates = candidates[: args.limit]

        counter: Counter[str] = Counter()
        samples: dict[str, list[dict]] = defaultdict(list)
        would_parse_details: list[dict] = []

        for opp in candidates:
            src = sources.get(opp.source_id) if opp.source_id else None
            reason, raw, parsed, country = classify_one(opp, src)
            # classify_one returns country only for parse paths; for early discards infer anyway for sample display
            if country is None:
                # still compute for display
                country = infer_country(opp, src)
            counter[reason] += 1

            # collect samples (up to 5 per reason, plus global would_parse)
            if len(samples[reason]) < 5:
                raw_snippet = ""
                if raw is not None:
                    raw_snippet = raw[:160].replace("\n", " ").replace("\r", " ")
                elif opp.funding_amount_raw:
                    raw_snippet = opp.funding_amount_raw[:160].replace("\n", " ").replace("\r", " ")
                elif opp.raw_text:
                    raw_snippet = opp.raw_text[:160].replace("\n", " ").replace("\r", " ")
                samples[reason].append(
                    {
                        "id": opp.id[:8] if opp.id else "?",
                        "full_id": opp.id,
                        "title": (opp.title or "")[:80],
                        "source_key": src.key if src else "no-source",
                        "country_infer": country,
                        "raw_snippet": raw_snippet,
                        "reason": reason,
                        "parsed": parsed,
                        "funding_raw": (opp.funding_amount_raw or "")[:60],
                    }
                )
            if reason == "WOULD_PARSE":
                would_parse_details.append(samples[reason][-1] if samples[reason] else {})

        # --- Summary sorted by count desc ---
        print()
        print("=== DISTRIBUTION BY FIRST DISCARD REASON (sorted desc) ===")
        for reason, count in counter.most_common():
            pct = (count / len(candidates) * 100) if candidates else 0
            print(f"  {reason:30} {count:5}  ({pct:5.1f}%)")

        would = counter.get("WOULD_PARSE", 0)
        would_pct = (would / len(candidates) * 100) if candidates else 0
        print()
        print(f" WOULD_PARSE: {would}/{len(candidates)} ({would_pct:.1f}%) — rows that pass all guards and parse to value+currency")
        print(f" DISCARDED  : {len(candidates) - would}/{len(candidates)} ({100 - would_pct:.1f}%)")

        if would > 0:
            print()
            print(" *** FINDING: hidden WOULD_PARSE rows exist — indicates backfill_022 guard may be hiding parseable funding (investigate) ***")
        else:
            print()
            print(" No WOULD_PARSE rows — all 1821 discards are correctly rejected by current guards (no hidden bug).")

        # --- Samples: top reasons + WOULD_PARSE ---
        print()
        print("=== SAMPLES (up to 5 per top reason + WOULD_PARSE) ===")
        # Show top 4 reasons by count, plus WOULD_PARSE if present
        top_reasons = [r for r, _ in counter.most_common(4)]
        if "WOULD_PARSE" not in top_reasons and would > 0:
            top_reasons.append("WOULD_PARSE")
        # Also ensure we cover interesting strict-guard reasons even if not top
        for must_show in ["no_currency_near_number", "no_funding_keyword", "parse_none", "cops_false_positive"]:
            if must_show in counter and must_show not in top_reasons:
                top_reasons.append(must_show)

        for reason in top_reasons:
            if reason not in samples:
                continue
            print(f"\n -- {reason} ({counter[reason]} total) --")
            for s in samples[reason][:5]:
                print(
                    f"  id={s['id']} | src={s['source_key']:20} | country={str(s['country_infer']):12} | title='{s['title']}'"
                )
                print(f"    raw_snippet: '{s['raw_snippet']}'")
                if s["parsed"]:
                    print(f"    parsed: {s['parsed']} | funding_raw_old: '{s['funding_raw']}'")
                print(f"    reason: {s['reason']}")

        # --- Strict guard audit: presupuesto + large number without currency ---
        print()
        print("=== STRICT GUARD AUDIT: presupuesto/monto with large number but maybe no currency symbol ===")
        # Count how many no_currency_near_number rows actually contain presupuesto.*\d{6,}
        audit_count = 0
        audit_samples: list[dict] = []
        for opp in candidates:
            src = sources.get(opp.source_id) if opp.source_id else None
            # quick check: raw contains presupuesto/monto/fondo + large number
            combined = " ".join(p for p in [opp.raw_text or "", opp.summary or "", opp.title or ""] if p)[:3000]
            if re.search(r"presupuesto|monto|fondo|financiac", combined, re.IGNORECASE) and re.search(r"\d{6,}", combined):
                # check if it would have been discarded for currency
                # we re-classify but focus on this pattern
                if _CURRENCY_NEAR_NUMBER_RE.search(combined) is None:
                    audit_count += 1
                    if len(audit_samples) < 5:
                        audit_samples.append(
                            {
                                "id": opp.id[:8],
                                "title": (opp.title or "")[:80],
                                "src": src.key if src else "no-source",
                                "snippet": combined[:160].replace("\n", " "),
                            }
                        )
        print(f" Rows with presupuesto/monto/fondo + 6+ digit number but NO currency-near-number: {audit_count}")
        for s in audit_samples:
            print(f"  id={s['id']} src={s['src']:20} title='{s['title']}' snippet='{s['snippet']}...'")
        if audit_count > 50:
            print(" -> MANY such rows: guard _CURRENCY_NEAR_NUMBER_RE may be too strict — consider relaxing to allow presupuesto.*\\d{{6,}} without currency (COP inference via infer_country).")
        elif audit_count > 0:
            print(" -> Few such rows: current guard is probably fine, but review samples above (maybe COP inference would help).")
        else:
            print(" -> None: no missed presupuesto-large-number rows hidden by currency guard.")

        print()
        print("=== END PROBE (idempotent, no commits) ===")

    finally:
        db.close()


if __name__ == "__main__":
    main()
