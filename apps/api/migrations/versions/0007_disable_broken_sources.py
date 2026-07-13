"""Disable 21 unrecoverable YELLOW and RED sources.

Revision ID: 0007_disable_broken_sources
Revises: 0006_connector_config
Create Date: 2026-07-13

Purpose:

After the scraper optimization pass (dfffeae) and the connector YELLOW fix
campaign (8bf07ed, 5dd760d), 21 sources remain unrecoverable:

- 404 pages (agrosavia, bndes, dane, dian, minsalud, invima, javeriana)
- WAF blocked (caf, fondo-nacional-garantias)
- JS-only (sebrae, sgc-colombia)
- DNS dead (fonacyt-bolivia, sennova-sena)
- SSL errors (uptc, minagricultura)
- Other (finep, uis 502, ideam unreachable, embrapii/faperj/innpulsa-startup timeout)

The seed definition list (d562ce2) marked these as enabled=False, but
seed_default_sources() always overrode that with enabled=True. With the
seed fix in place, this migration permanently disables the existing rows.
"""

from __future__ import annotations

import logging

from alembic import op
from sqlalchemy import text

logger = logging.getLogger(__name__)

revision = "0007_disable_broken_sources"
down_revision = "0006"
branch_labels = None
depends_on = None

BROKEN_KEYS = [
    "fondo-nacional-garantias",
    "invima-convocatorias",
    "agrosavia-convocatorias",
    "dane-convocatorias",
    "ideam-convocatorias",
    "sgc-colombia",
    "innpulsa-colombia-startup",
    "dian-contratacion",
    "fonacyt-bolivia",
    "caf-convocatorias",
    "minagricultura-convocatorias",
    "minsalud-convocatorias",
    "uis-investigacion",
    "javeriana-investigacion",
    "uptc-investigacion",
    "sennova-sena",
    "finep-brasil",
    "embrapii-brasil",
    "faperj-brasil",
    "sebrae-brasil",
    "bndes-brasil",
]


def upgrade() -> None:
    conn = op.get_bind()
    for key in BROKEN_KEYS:
        result = conn.execute(
            text("UPDATE sources SET enabled = :val WHERE key = :key AND enabled != :val"),
            {"val": False, "key": key},
        )
        if result.rowcount:
            logger.info("Disabled source key=%s (%d row(s))", key, result.rowcount)


def downgrade() -> None:
    conn = op.get_bind()
    for key in BROKEN_KEYS:
        conn.execute(
            text("UPDATE sources SET enabled = :val WHERE key = :key AND enabled != :val"),
            {"val": True, "key": key},
        )
