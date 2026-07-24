"""Backfill: recalcular status y limpiar URLs rotas de oportunidades existentes.

Tres fases:
  1. Recalcular status según close_date: oportunidades con close_date < now()
     pasan a "closed"; las que cierran pronto pasan a "closing_soon".
  2. Limpiar official_url/application_url que ya no son reachables (HTTP error).
  3. (Opcional) Mostrar reporte de cambios.

Usage:
    python scripts/backfill_opportunity_status.py                   # aplicar cambios
    python scripts/backfill_opportunity_status.py --dry-run          # solo previsualizar
    python scripts/backfill_opportunity_status.py --batch-size 100   # lotes de 100
    python scripts/backfill_opportunity_status.py --skip-url-check   # saltar validacion de URLs
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Opportunity, OpportunityStatus
from app.services import inferred_opportunity_status, opportunity_status, url_is_reachable


def _combined_text(opp: Opportunity) -> str:
    return " ".join(
        part for part in [opp.title, opp.summary, opp.description, opp.raw_text] if part
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill: recalcular status y limpiar URLs rotas de oportunidades existentes",
    )
    parser.add_argument("--dry-run", action="store_true", help="Mostrar cambios sin aplicar")
    parser.add_argument("--batch-size", type=int, default=200, help="Registros por lote (default: 200)")
    parser.add_argument("--skip-url-check", action="store_true", help="Saltar validacion de URLs")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        total = db.scalar(select(func.count()).select_from(Opportunity)) or 0
        if total == 0:
            print("No hay oportunidades — nada que hacer.")
            sys.exit(0)

        now = datetime.now(UTC).replace(tzinfo=None)
        settings = get_settings()
        soon_days = settings.scraping_closing_soon_days

        # ---- Fase 1: recalcular status ----
        print(f"\n{'='*60}")
        print(f"FASE 1: Recalcular status ({total} oportunidades)")
        print(f"{'='*60}")

        # Encontrar oportunidades cuyo status NO coincide con su close_date
        status_changes = {"open": 0, "closed": 0, "closing_soon": 0, "unknown": 0}
        status_errors = 0
        url_cleared = 0
        app_url_cleared = 0

        offset = 0
        batch = args.batch_size
        processed = 0

        while True:
            rows = (
                db.execute(
                    select(Opportunity)
                    .order_by(Opportunity.created_at.desc())
                    .offset(offset)
                    .limit(batch)
                )
                .scalars()
                .all()
            )
            if not rows:
                break

            for opp in rows:
                try:
                    text = _combined_text(opp)
                    correct_status = inferred_opportunity_status(opp.close_date, text)
                    if opp.status != correct_status:
                        if args.dry_run:
                            print(
                                f"  · {opp.title[:60]:60s}  {opp.status:15s} → {correct_status:15s}"
                                f"  (cierre: {opp.close_date.date() if opp.close_date else 'N/A'})"
                            )
                        else:
                            opp.status = correct_status
                            opp.updated_at = now
                        status_changes[correct_status] = status_changes.get(correct_status, 0) + 1
                except Exception as exc:
                    status_errors += 1
                    print(f"  ⚠ Error calculando status para {opp.id}: {exc}", file=sys.stderr)

                # ---- Fase 2: limpiar URLs rotas ----
                if not args.skip_url_check:
                    if opp.official_url and not url_is_reachable(opp.official_url):
                        if args.dry_run:
                            print(f"  · URL rota (official): {opp.official_url[:80]}")
                        else:
                            opp.official_url = None
                            opp.updated_at = now
                        url_cleared += 1
                    if opp.application_url and not url_is_reachable(opp.application_url):
                        if args.dry_run:
                            print(f"  · URL rota (application): {opp.application_url[:80]}")
                        else:
                            opp.application_url = None
                            opp.updated_at = now
                        app_url_cleared += 1

            if not args.dry_run:
                db.commit()
            processed += len(rows)
            offset += len(rows)
            elapsed = max(time.process_time(), 0.001)
            rate = processed / elapsed if elapsed > 0 else 0
            print(f"  ✓ {processed}/{total} — {status_changes} cambios de status, {url_cleared} URLs oficiales limpias, {app_url_cleared} URLs aplicacion limpias ({rate:.0f} ops/s)")

            if len(rows) < batch:
                break

        total_changes = sum(status_changes.values())
        total_url_changes = url_cleared + app_url_cleared

        print(f"\n{'='*60}")
        print(f"RESUMEN")
        print(f"{'='*60}")
        print(f"  Procesadas:     {processed}")
        print(f"  Status cambiados: {total_changes}")
        if not args.skip_url_check:
            print(f"  URLs oficiales limpias: {url_cleared}")
            print(f"  URLs aplicacion limpias: {app_url_cleared}")
        if status_errors:
            print(f"  Errores:        {status_errors}")
        if args.dry_run:
            print(f"\n  🟡 DRY RUN — no se aplicaron cambios. Ejecutar sin --dry-run para aplicar.")
        else:
            print(f"\n  ✅ Cambios aplicados.")
        sys.exit(0)

    finally:
        db.close()


if __name__ == "__main__":
    main()
