"""Activa reject_news en 2 fuentes que mezclan noticias con convocatorias (T2b).

Revision ID: 0020_reject_news_cundinamarca_bogota
Revises: 0019_canonical_source_urls

Las filas existentes en ``sources`` no se actualizan con reseed normal
(solo toca filas sin ownership), así que el flag nuevo de seed.py
(``connector_config.reject_news=true``) se lleva a las 2 filas con esta
migración: merge de la clave dentro del JSON existente (read-modify-write
en Python, portable SQLite/Postgres), sin tocar el resto del config.

No toca ninguna otra clave.
"""

import json

from alembic import op
from sqlalchemy import text

revision = "0020_reject_news_cundinamarca_bogota"
down_revision = "0019_canonical_source_urls"
branch_labels = None
depends_on = None

TARGET_KEYS = (
    "cundinamarca-convocatorias",
    "bogota-desarrollo-economico",
)


def _apply(add: bool) -> None:
    bind = op.get_bind()
    for key in TARGET_KEYS:
        current = bind.execute(
            text("SELECT connector_config FROM sources WHERE key = :key"),
            {"key": key},
        ).scalar()
        try:
            config = json.loads(current) if current else {}
        except (TypeError, ValueError):
            config = {}
        if not isinstance(config, dict):
            config = {}
        if add:
            config["reject_news"] = True
        else:
            config.pop("reject_news", None)
        bind.execute(
            text(
                "UPDATE sources SET connector_config = :config, "
                "updated_at = CURRENT_TIMESTAMP WHERE key = :key"
            ),
            {"key": key, "config": json.dumps(config)},
        )


def upgrade() -> None:
    _apply(add=True)


def downgrade() -> None:
    _apply(add=False)
