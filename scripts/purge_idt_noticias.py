"""Purge stored IDT newsroom rows (source `idt-noticias`).

Dictamen E13 (odd/tasks/enriquecimiento-detalle.md): idt-noticias raspa el
noticiero del IDT (https://www.idt.gov.co/noticias) y sus notas caían en el
sector turismo del informe. Acuerdo 2026-10-15: sólo se reportan
convocatorias. La fuente ya quedó deshabilitada en seed.py; este script
elimina las filas ya guardadas.

Uso (desde la raíz del repo):
    python scripts/purge_idt_noticias.py            # dry-run, sólo cuenta
    python scripts/purge_idt_noticias.py --apply    # respalda y purga

Con --apply primero escribe un respaldo JSON en reports/ y sólo después
borra. La fila Source se conserva (deshabilitada) para no romper seed.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apps", "api"))

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import (
    Alert,
    Opportunity,
    OpportunityAxisMatch,
    OpportunityDocument,
    OpportunityEmbedding,
    OpportunityScore,
    Source,
)

SOURCE_KEY = "idt-noticias"


def _backup_path() -> Path:
    override = os.environ.get("PURGE_BACKUP_DIR")
    if override:
        base = Path(override)
    else:
        base = Path(__file__).resolve().parents[1] / "reports"  # repo root
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return base / f"purge-{SOURCE_KEY}-{stamp}.json"


def main(apply: bool) -> int:
    with SessionLocal() as db:
        source = db.scalar(select(Source).where(Source.key == SOURCE_KEY))
        if source is None:
            print("not-found: no existe Source con key=idt-noticias")
            return 1
        opp_ids = list(
            db.scalars(select(Opportunity.id).where(Opportunity.source_id == source.id))
        )
        dependents = {
            "documents": db.scalar(
                select(OpportunityDocument.id).where(
                    OpportunityDocument.opportunity_id.in_(opp_ids)
                )
            )
            is not None,
            "scores": db.scalar(
                select(OpportunityScore.id).where(OpportunityScore.opportunity_id.in_(opp_ids))
            )
            is not None,
            "embeddings": db.scalar(
                select(OpportunityEmbedding.id).where(
                    OpportunityEmbedding.opportunity_id.in_(opp_ids)
                )
            )
            is not None,
            "axis_matches": db.scalar(
                select(OpportunityAxisMatch.id).where(
                    OpportunityAxisMatch.opportunity_id.in_(opp_ids)
                )
            )
            is not None,
            "alerts": db.scalar(
                select(Alert.id).where(Alert.opportunity_id.in_(opp_ids))
            )
            is not None,
        }
        rows = db.scalars(
            select(Opportunity).where(Opportunity.source_id == source.id)
        ).all()
        print(
            f"source={source.key} enabled={source.enabled} "
            f"opportunities={len(rows)} dependents={dependents}"
        )
        if not apply:
            print("dry-run: nada borrado (usá --apply para purgar con respaldo)")
            return 0
        backup = {
            "source_key": SOURCE_KEY,
            "source_id": source.id,
            "purged_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "opportunities": [
                {
                    "id": o.id,
                    "title": o.title,
                    "official_url": o.official_url,
                    "application_url": o.application_url,
                    "status": o.status,
                    "sector": o.sector,
                    "first_seen_at": o.first_seen_at.isoformat() if o.first_seen_at else None,
                }
                for o in rows
            ],
        }
        path = _backup_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"backup: {path} ({len(rows)} filas)")
        for model in (
            OpportunityDocument,
            OpportunityScore,
            OpportunityEmbedding,
            OpportunityAxisMatch,
            Alert,
        ):
            db.execute(
                model.__table__.delete().where(model.opportunity_id.in_(opp_ids))
            )
        db.execute(Opportunity.__table__.delete().where(Opportunity.source_id == source.id))
        db.commit()
        print(f"purged {len(rows)} opportunities de {SOURCE_KEY}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main("--apply" in sys.argv[1:]))
