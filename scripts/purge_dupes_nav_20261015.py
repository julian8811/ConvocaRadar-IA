"""Purge NIH duplicates + Brazil nav junk (auditoría 2026-10-15).

- grants-gov-rss: 449 found / 0 created en 30d; sus 24 filas existen
  duplicadas en grants-gov / simpler-grants. La fuente queda deshabilitada.
- anp/capes/inct: 5 filas con labels de navegación como título
  ("Acesso à Informação", "Ações e Programas"). Solo match exacto.

Uso (desde la raíz del repo, o vía stdin en el servidor como E9):
    python scripts/purge_dupes_nav_20261015.py            # dry-run
    python scripts/purge_dupes_nav_20261015.py --apply    # respalda y purga
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

SOURCE_KEYS = ("grants-gov-rss",)
NAV_TITLES = ("Acesso à Informação", "Ações e Programas")

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
    return base / f"purge-dupes-nav-{stamp}.json"


def main(apply: bool) -> int:
    with SessionLocal() as db:
        by_source = list(
            db.scalars(
                select(Opportunity).where(
                    Opportunity.source_id.in_(
                        select(Source.id).where(Source.key.in_(SOURCE_KEYS))
                    )
                )
            )
        )
        by_title = list(db.scalars(select(Opportunity).where(Opportunity.title.in_(NAV_TITLES))))
        rows = {o.id: o for o in [*by_source, *by_title]}.values()
        rows = list(rows)
        print("por_fuente=%d por_titulo=%d total=%d" % (len(by_source), len(by_title), len(rows)))
        if not apply:
            print("dry-run: nada borrado (usá --apply para purgar con respaldo)")
            return 0
        backup = {
            "source_keys": list(SOURCE_KEYS),
            "nav_titles": list(NAV_TITLES),
            "purged_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "reason": "duplicados NIH + nav-junk BR (auditoría 2026-10-15)",
            "opportunities": [
                {"id": o.id, "title": o.title, "official_url": o.official_url,
                 "status": o.status}
                for o in rows
            ],
        }
        path = _backup_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
        print("backup: %s (%d filas)" % (path, len(rows)))
        ids = [o.id for o in rows]
        for model in _DEPENDENTS:
            db.execute(model.__table__.delete().where(model.opportunity_id.in_(ids)))
        db.execute(Opportunity.__table__.delete().where(Opportunity.id.in_(ids)))
        db.commit()
        print("purged %d filas" % len(rows))
        return 0


if __name__ == "__main__":
    raise SystemExit(main("--apply" in sys.argv[1:]))
