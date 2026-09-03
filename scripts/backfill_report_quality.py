"""Backfill integral de calidad de datos para informes.

Repara los huecos que arruinan los informes mensuales sobre las filas
ya ingestadas:
  1. raw_text JSON (Grants.gov) -> agency/openDate/closeDate/estado reales.
  2. close_date faltante        -> backfill_close_dates + extractor local.
  3. funding_amount faltante    -> parser oficial + extractor local.
  4. Resumenes basura           -> resumen construido con datos estructurados.
  5. Entidad generica (= fuente o fallback) -> agencia explicita conocida.
  6. status desactualizado      -> recálculo inferred_opportunity_status.

Deterministico y sin red: usa los extractores locales de la plataforma.
El backfill IA remoto puede correr después desde admin cuando haya cuota.

Usage:
    python scripts/backfill_report_quality.py                # aplicar
    python scripts/backfill_report_quality.py --dry-run      # previsualizar
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime

from sqlalchemy import or_, select

from app.core.ai import build_local_extraction
from app.db.session import SessionLocal
from app.models import Opportunity, Source
from app.services import (
    _parse_ai_close_date,
    _parse_funding_amount,
    backfill_close_dates,
    backfill_funding_amounts,
    inferred_opportunity_status,
)

GENERIC_ENTITIES = {"simpler grants", "grants.gov", "developmentaid"}
DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d")


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def is_junk_summary(summary: str | None) -> bool:
    s = (summary or "").strip()
    if len(s) <= 40:
        return True
    if re.match(r"^\s*(number|opportunity\s+number|notice)\s*[:：]", s, re.IGNORECASE):
        return True
    if "| status:" in s.lower():
        return True
    if s.lower().startswith(("sitemap entry", "title ", "http")):
        return True
    return False


def _combined(opp: Opportunity) -> str:
    return " ".join(
        part for part in [opp.title, opp.summary, opp.description, opp.raw_text] if part
    )


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def _json_payload(opp: Opportunity) -> dict | None:
    rt = (opp.raw_text or "").strip()
    if not rt.startswith("{"):
        return None
    try:
        data = json.loads(rt)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _build_summary(opp: Opportunity, extra: dict | None = None) -> str:
    """Resumen factual desde campos estructurados disponibles."""
    parts: list[str] = []
    agency = (extra or {}).get("agency") or opp.entity
    if agency:
        parts.append(f"Convocatoria de {agency}")
    amount = opp.funding_amount_raw or (extra or {}).get("amount")
    if amount:
        parts.append(f"financiamiento: {amount}")
    if opp.open_date:
        parts.append(f"abre el {opp.open_date.date().isoformat()}")
    if opp.close_date:
        parts.append(f"cierra el {opp.close_date.date().isoformat()}")
    if not parts:
        return ""
    return ". ".join([parts[0]] + [p[0].upper() + p[1:] for p in parts[1:]]) + "."


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill de calidad: fechas, montos, resumenes, entidad y estado",
    )
    parser.add_argument("--dry-run", action="store_true", help="No escribir cambios")
    args = parser.parse_args()

    db = SessionLocal()
    stats = {
        "json_repair": 0,
        "close_date_regex": 0,
        "close_date_local": 0,
        "amount_value_parsed": 0,
        "amount_raw_found": 0,
        "summaries_fixed": 0,
        "entity_enriched": 0,
        "status_recalc": 0,
    }
    try:
        org_ids = [
            row[0]
            for row in db.execute(select(Opportunity.organization_id).distinct()).all()
        ]
        scope_org_id = next((o for o in org_ids if o), None)
        sources = {s.id: s.name for s in db.scalars(select(Source)).all()}
        now = datetime.now(UTC).replace(tzinfo=None)
        scope = or_(
            Opportunity.organization_id == scope_org_id,
            Opportunity.organization_id.is_(None),
        )
        all_opps = list(db.scalars(select(Opportunity).where(scope)))

        def save(opp: Opportunity) -> None:
            if not args.dry_run:
                opp.updated_at = now

        # ── 1. Reparar filas cuyo raw_text es JSON estructurado ───────────
        for opp in all_opps:
            data = _json_payload(opp)
            if not data:
                continue
            changed = False
            agency = str(data.get("agency") or "").strip()
            if agency and len(agency) >= 4 and _norm(agency) != _norm(opp.entity):
                opp.entity = agency
                changed = True
            close_dt = _parse_date(str(data.get("closeDate") or ""))
            if close_dt and not opp.close_date:
                opp.close_date = close_dt
                changed = True
            open_dt = _parse_date(str(data.get("openDate") or ""))
            if open_dt and not opp.open_date:
                opp.open_date = open_dt
                changed = True
            if changed or is_junk_summary(opp.summary):
                opp.summary = _build_summary(opp)
                changed = True
            if changed:
                save(opp)
                stats["json_repair"] += 1
        print(f"1. filas reparadas desde JSON embebido: {stats['json_repair']}")

        # ── 2. Fechas de cierre: servicio oficial (regex) ──────────────────
        if not args.dry_run and scope_org_id:
            res = backfill_close_dates(db, scope_org_id, limit=1000)
            stats["close_date_regex"] = res["updated"]
        print(f"2. close_date via backfill_close_dates: {stats['close_date_regex']}")

        remaining = [o for o in db.scalars(select(Opportunity).where(scope)) if not o.close_date]
        for opp in remaining:
            text = _combined(opp)
            if not text.strip():
                continue
            parsed = _parse_ai_close_date(build_local_extraction(text).get("close_date"))
            if parsed:
                opp.close_date = parsed
                opp.status = inferred_opportunity_status(parsed, text)
                save(opp)
                stats["close_date_local"] += 1
        print(f"2b. close_date via extractor local: {stats['close_date_local']}")

        # ── 3. Montos ──────────────────────────────────────────────────────
        if not args.dry_run and scope_org_id:
            res = backfill_funding_amounts(db, scope_org_id, limit=1000)
            stats["amount_value_parsed"] = res["updated"]
        print(f"3. funding value parseado: {stats['amount_value_parsed']}")

        for opp in db.scalars(select(Opportunity).where(scope)):
            if opp.funding_amount_raw:
                continue
            raw = build_local_extraction(_combined(opp)).get("funding_amount_raw")
            if isinstance(raw, str) and raw.strip():
                opp.funding_amount_raw = raw.strip()
                value, currency = _parse_funding_amount(raw.strip())
                if value is not None:
                    opp.funding_amount_value = value
                    opp.funding_amount_currency = currency
                save(opp)
                stats["amount_raw_found"] += 1
        print(f"3b. funding raw encontrado: {stats['amount_raw_found']}")

        # ── 4. Resumenes basura restantes ──────────────────────────────────
        for opp in all_opps:
            if not is_junk_summary(opp.summary):
                continue
            candidate = _build_summary(opp)
            if candidate and _norm(candidate) != _norm(opp.summary):
                opp.summary = candidate
                save(opp)
                stats["summaries_fixed"] += 1
        print(f"4. resumenes reconstruidos: {stats['summaries_fixed']}")

        # ── 5. Entidad generica -> agencia explicita en texto ─────────────
        agency_re = re.compile(r"\bAgency\s*[:：]\s*([^\n|]{4,80})", re.IGNORECASE)
        for opp in all_opps:
            src_name = sources.get(opp.source_id, "")
            generic = (
                _norm(opp.entity) == _norm(src_name)
                or _norm(opp.entity) in GENERIC_ENTITIES
            )
            if not generic:
                continue
            m = agency_re.search(_combined(opp))
            if not m:
                continue
            agency = re.sub(r"\s+", " ", m.group(1)).strip(" .,-")
            if (
                len(agency) >= 4
                and not agency.lower().startswith("http")
                and _norm(agency) not in {_norm(opp.entity), _norm(src_name)}
            ):
                opp.entity = agency
                save(opp)
                stats["entity_enriched"] += 1
        print(f"5. entidades enriquecidas: {stats['entity_enriched']}")

        # ── 6. Recalcular status global ────────────────────────────────────
        for opp in db.scalars(select(Opportunity).where(scope)):
            correct = inferred_opportunity_status(
                opp.close_date,
                " ".join([opp.summary or "", opp.raw_text or ""]),
            )
            if opp.status != correct:
                opp.status = correct
                save(opp)
                stats["status_recalc"] += 1
        print(f"6. status recalculados: {stats['status_recalc']}")

        if not args.dry_run:
            db.commit()
            print("\nCambios aplicados.")
        else:
            print("\nDRY RUN — no se escribio nada.")
        print("RESUMEN:", stats)
        sys.exit(0)
    finally:
        db.close()


if __name__ == "__main__":
    main()
