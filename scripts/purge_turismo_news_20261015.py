"""Purge news rows from the turismo sector (sources other than IDT).

Contexto: tras deshabilitar idt-noticias (E13, sólo-convocatorias), la
revisión del sector turismo mostró 9 noticias de otras 5 fuentes legítimas
(procolombia, bogota-desarrollo-economico, bogota-cultura-recreacion,
cundinamarca, uniandes). Esas fuentes son convocatorias reales — NO se
deshabilitan; sólo se purgan las filas-noticia por ID exacto.

NO se purgan (criterio documentado 2026-10-15): anuncios de convocatorias
aunque sean pobres en datos (premios 2024, cortometrajes, inscripción a
guianza, MinCIT sin fecha) ni eventos ambiguos (Foro Internacional). Un ban
por URL rompería fixtures legítimos (test_032 medellín sala-de-prensa,
test_034 PICTE /noticias/): el gate sistémico correcto es por evidencia de
convocatoria, pendiente como trabajo futuro.

Uso (desde la raíz del repo, o vía stdin en el servidor como E9):
    python scripts/purge_turismo_news_20261015.py            # dry-run
    python scripts/purge_turismo_news_20261015.py --apply    # respalda y purga
    PURGE_BACKUP_DIR=/tmp/purge-bk python scripts/purge_turismo_news_20261015.py --apply
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apps", "api"))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Alert,
    Opportunity,
    OpportunityAxisMatch,
    OpportunityDocument,
    OpportunityEmbedding,
    OpportunityScore,
)

# IDs verificados en producción 2026-10-15 (sector turismo, filas-noticia).
PURGE_IDS = (
    "2d17931b-a2d2-4c4a-949e-38427e7ab380",  # Jazz al Parque (cultura)
    "82c8641f-e118-40ee-9f0b-66e17f2d6a17",  # turismo médico (bogota-d.e.)
    "0a508a40-5f33-41e1-be65-1d0a874247ef",  # Festival Cordillera (bogota-d.e.)
    "86db3add-be7d-4421-83ac-e5aa1a730205",  # fin de semana turistas (bogota-d.e.)
    "cb7bfcbb-2870-4576-8ed9-ceebb379dfd0",  # Bandas ganadores (cundinamarca)
    "fe8933c8-25d9-454c-b10d-dbcc0ec420ba",  # Premios 2023 (procolombia, vencida)
    "c5e1b843-fd3a-4aed-853f-eb7d8cb0e291",  # misión comercial Australia (procolombia)
    "f7b5ee74-8ad6-4809-98e6-f10716b6e6e5",  # Premios 2023 extiende (procolombia)
    "01a9f654-93f8-48e7-b27c-10830eb71703",  # Museos gana convocatoria (uniandes)
)

_DEPENDENTS = (
    OpportunityDocument,
    OpportunityScore,
    OpportunityEmbedding,
    OpportunityAxisMatch,
    Alert,
)


def _backup_path() -> Path:
    override = os.environ.get("PURGE_BACKUP_DIR")
    base = Path(override) if override else Path(__file__).resolve().parents[1] / "reports"
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return base / f"purge-turismo-news-{stamp}.json"


def main(apply: bool) -> int:
    with SessionLocal() as db:
        rows = db.scalars(select(Opportunity).where(Opportunity.id.in_(PURGE_IDS))).all()
        found = {o.id for o in rows}
        missing = [i for i in PURGE_IDS if i not in found]
        print(f"encontradas={len(rows)} faltantes={missing}")
        for o in rows:
            print(f"  - {o.title[:70]}")
        if not apply:
            print("dry-run: nada borrado (usá --apply para purgar con respaldo)")
            return 0
        if missing:
            raise SystemExit(f"abortado: IDs no encontrados {missing}")
        backup = {
            "purged_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "reason": "noticias en sector turismo (sólo-convocatorias 2026-10-15)",
            "opportunities": [
                {
                    "id": o.id,
                    "title": o.title,
                    "official_url": o.official_url,
                    "status": o.status,
                    "sector": o.sector,
                }
                for o in rows
            ],
        }
        path = _backup_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"backup: {path} ({len(rows)} filas)")
        for model in _DEPENDENTS:
            db.execute(model.__table__.delete().where(model.opportunity_id.in_(PURGE_IDS)))
        db.execute(Opportunity.__table__.delete().where(Opportunity.id.in_(PURGE_IDS)))
        db.commit()
        print(f"purged {len(rows)} noticias de turismo")
        return 0


if __name__ == "__main__":
    raise SystemExit(main("--apply" in sys.argv[1:]))
