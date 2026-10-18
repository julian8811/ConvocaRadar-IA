"""Completa connector_config en 2 filas que estaban en NULL (T2b fix-forward).

Revision ID: 0021_reject_news_full_config
Revises: 0020_reject_news_cundinamarca_bogota

Contexto: la 0020 mergeó ``reject_news`` sobre el JSON existente, pero en
prod esas 2 filas tenían ``connector_config`` NULL (el seed nunca llegó:
reseed solo muta filas sin ownership). Resultado: quedaron con
``{'reject_news': true}`` y la factory las rutea a ConfigurableHtml con
config incompleta → ValueError en cada run.

Esta migración escribe el config COMPLETO previsto en seed.py
(misma fuente de verdad) + ``reject_news: true``. Downgrade: vuelve a
NULL (estado pre-0020/0021, verificado en prod 2026-10-18).
"""

import json

from alembic import op
from sqlalchemy import text

revision = "0021_reject_news_full_config"
down_revision = "0020_reject_news_cundinamarca_bogota"
branch_labels = None
depends_on = None

FULL_CONFIGS = {
    "bogota-desarrollo-economico": {
        "list_selectors": [
            "article",
            "a[href*='/mi-ciudad/desarrollo-economico/']",
            "a[href*='convocat']",
            "a[href*='oportun']",
        ],
        "title_selectors": ["h2", "h3", "a"],
        "link_selectors": ["a"],
        "content_selectors": ["article", "main", "a"],
        "date_labels": ["Cierre:", "Deadline:"],
        "detail_enrichment": False,
        "reject_news": True,
    },
    "cundinamarca-convocatorias": {
        "list_selectors": ["article", ".views-row", "main a"],
        "title_selectors": ["h2", "h3", "a"],
        "link_selectors": ["a"],
        "content_selectors": ["article", "main"],
        "date_labels": ["Cierre:", "Deadline:"],
        "detail_enrichment": False,
        "reject_news": True,
    },
}


def upgrade() -> None:
    bind = op.get_bind()
    for key, config in FULL_CONFIGS.items():
        bind.execute(
            text(
                "UPDATE sources SET connector_config = :config, "
                "updated_at = CURRENT_TIMESTAMP WHERE key = :key"
            ),
            {"key": key, "config": json.dumps(config)},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for key in FULL_CONFIGS:
        bind.execute(
            text(
                "UPDATE sources SET connector_config = NULL, "
                "updated_at = CURRENT_TIMESTAMP WHERE key = :key"
            ),
            {"key": key},
        )
