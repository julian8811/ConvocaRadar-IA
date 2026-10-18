"""Deshabilita unwomen-innovate en filas existentes (purge trio 2026-10-18).

Revision ID: 0022_disable_unwomen_innovate
Revises: 0021_reject_news_full_config

Contexto: la página fuente es institucional sin convocatorias (45/45 filas
sin fecha ni monto, muestreo prod 2026-10-18; acuerdo sólo-convocatorias).
seed.py ya la declara con ``enabled=False``, pero el reseed solo muta filas
sin ownership (L6) y la fila de prod tiene owner → el flag no llegaría.
Esta migración aplica el disable a la fila existente, igual que la 0007
para las 21 fuentes rotas. Downgrade: vuelve a enabled=True (estado previo,
el seed no declaraba ``enabled`` → default True).

No toca ninguna otra clave.
"""

from __future__ import annotations

import logging

from alembic import op
from sqlalchemy import text

logger = logging.getLogger(__name__)

revision = "0022_disable_unwomen_innovate"
down_revision = "0021_reject_news_full_config"
branch_labels = None
depends_on = None

TARGET_KEY = "unwomen-innovate"


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(
        text("UPDATE sources SET enabled = :val WHERE key = :key AND enabled != :val"),
        {"val": False, "key": TARGET_KEY},
    )
    if result.rowcount:
        logger.info("Disabled source key=%s (%d row(s))", TARGET_KEY, result.rowcount)


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text("UPDATE sources SET enabled = :val WHERE key = :key AND enabled != :val"),
        {"val": True, "key": TARGET_KEY},
    )
