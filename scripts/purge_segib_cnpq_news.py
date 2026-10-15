"""Purge stored rows from newsroom sources (segib-noticias, cnpq-brasil).

Auditoría 2026-10-15: de 211 fuentes solo 3 son noticieros (idt ya resuelta).
segib-noticias trae 33 eventos/foros y cnpq-brasil 3 restos de navegación;
ambas quedan deshabilitadas en seed.py (acuerdo sólo-convocatorias). Este
script purga sus filas con respaldo JSON previo; las filas Source se
conservan deshabilitadas.

Uso (desde la raíz del repo, o vía stdin en el servidor como E9):
    python scripts/purge_segib_cnpq_news.py            # dry-run
    python scripts/purge_segib_cnpq_news.py --apply    # respalda y purga
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
    Source,
)

SOURCE_KEYS = ("segib-noticias", "cnpq-brasil")

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
    return base / f"purge-segib-cnpq-news-{stamp}.json"


def main(apply: bool) -> int:
    with SessionLocal() as db:
        sources = list(db.scalars(select(Source).where(Source.key.in_(SOURCE_KEYS))))
        found = {s.key for s in sources}
        missing = [k for k in SOURCE_KEYS if k not in found]
        if missing:
            print("sources faltantes: %s" % missing)
            return 1
        ids = [s.id for s in sources]
        rows = list(db.scalars(select(Opportunity).where(Opportunity.source_id.in_(ids))))
        print("fuentes=%s opportunities=%d" % (sorted(found), len(rows)))
        if not apply:
            print("dry-run: nada borrado (usá --apply para purgar con respaldo)")
            return 0
        backup = {
            "source_keys": sorted(found),
            "purged_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "reason": "noticieros (auditoría sólo-convocatorias 2026-10-15)",
            "opportunities": [
                {
                    "id": o.id,
                    "title": o.title,
                    "official_url": o.official_url,
                    "status": o.status,
                }
                for o in rows
            ],
        }
        path = _backup_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
        print("backup: %s (%d filas)" % (path, len(rows)))
        for model in _DEPENDENTS:
            db.execute(
                model.__table__.delete().where(model.opportunity_id.in_(
                    [o.id for o in rows]
                ))
            )
        db.execute(Opportunity.__table__.delete().where(Opportunity.source_id.in_(ids)))
        db.commit()
        print("purged %d filas de %s" % (len(rows), sorted(found)))
        return 0


if __name__ == "__main__":
    raise SystemExit(main("--apply" in sys.argv[1:]))
