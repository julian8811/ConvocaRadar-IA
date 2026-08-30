"""Reclassify experimental sources from daily to weekly.

Revision ID: 0013_reclassify_experimental_frequency
Revises: 0012_fix_sena_allowed_domains
"""

from alembic import op
from sqlalchemy import text

revision = "0013_reclassify_experimental_frequency"
down_revision = "0012_fix_sena_allowed_domains"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # Move experimental tier (and tier IS NULL legacy rows) from daily to weekly
    conn.execute(
        text(
            """
            UPDATE sources
            SET scraping_frequency = 'weekly',
                updated_at = CURRENT_TIMESTAMP
            WHERE scraping_frequency = 'daily'
              AND (tier = 'experimental' OR tier IS NULL)
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    # Revert: experimental weekly back to daily (best-effort)
    conn.execute(
        text(
            """
            UPDATE sources
            SET scraping_frequency = 'daily',
                updated_at = CURRENT_TIMESTAMP
            WHERE scraping_frequency = 'weekly'
              AND tier = 'experimental'
            """
        )
    )
