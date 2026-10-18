"""Deshabilita fuentes con yield cero verificado (T1/T2 2026-10-18).

Revision ID: 0023_disable_zero_yield_sources
Revises: 0022_disable_unwomen_innovate

Contexto: dane-convocatorias, idb-calls-proposals y sicon-bogota-estimulos
tienen 0 filas + last_item_count=0 + consecutive_empty_runs=5;
ascun-convocatorias rinde 200 parsed/0 válidos (feed 100% noticias tras
el filtro T2b). seed.py ya las declara con ``enabled=False``, pero el
reseed solo muta filas sin ownership (L6) y las filas de prod tienen
owner → el flag no llegaría. Esta migración aplica el disable a las filas
existentes, igual que la 0007 y la 0022. Downgrade: vuelve a enabled=True
(estado previo). No toca ninguna otra clave (todas tienen 0 filas: nada
que purgar).
"""

from __future__ import annotations

import logging

from alembic import op
from sqlalchemy import text

logger = logging.getLogger(__name__)

revision = "0023_disable_zero_yield_sources"
down_revision = "0022_disable_unwomen_innovate"
branch_labels = None
depends_on = None

TARGET_KEYS = (
    "dane-convocatorias",
    "idb-calls-proposals",
    "sicon-bogota-estimulos",
    "ascun-convocatorias",
)


def upgrade() -> None:
    conn = op.get_bind()
    for key in TARGET_KEYS:
        result = conn.execute(
            text("UPDATE sources SET enabled = :val WHERE key = :key AND enabled != :val"),
            {"val": False, "key": key},
        )
        if result.rowcount:
            logger.info("Disabled source key=%s (%d row(s))", key, result.rowcount)


def downgrade() -> None:
    conn = op.get_bind()
    for key in TARGET_KEYS:
        conn.execute(
            text("UPDATE sources SET enabled = :val WHERE key = :key AND enabled != :val"),
            {"val": True, "key": key},
        )
