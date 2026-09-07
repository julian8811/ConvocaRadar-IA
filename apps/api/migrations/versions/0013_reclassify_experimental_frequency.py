"""Reclassify experimental sources from daily to weekly.

Revision ID: 0013_reclassify_experimental_frequency
Revises: 0012_fix_sena_allowed_domains

Alembic creates ``alembic_version.version_num`` as VARCHAR(32) by default.
This repository started using revision identifiers longer than 32 characters
at 0013, so a fresh PostgreSQL database must widen the metadata column before
Alembic records this revision as current.
"""

from alembic import op
from sqlalchemy import text

revision = "0013_reclassify_experimental_frequency"
down_revision = "0012_fix_sena_allowed_domains"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        conn.execute(text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)"))

    # Move experimental tier (and tier IS NULL legacy rows) from daily to weekly.
    # Allowlist + manual override win: skip if key in allowlist or connector_config has manual_frequency.
    conn.execute(
        text(
            """
            UPDATE sources
            SET scraping_frequency = 'weekly',
                updated_at = CURRENT_TIMESTAMP
            WHERE scraping_frequency = 'daily'
              AND (tier = 'experimental' OR tier IS NULL)
              AND key NOT IN ('grants-gov', 'grants-gov-rss', 'nsf-funding-rss', 'eic-accelerator')
              AND (connector_config IS NULL OR CAST(connector_config AS TEXT) NOT LIKE '%manual_frequency%')
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    # Keep version_num widened: later revisions also exceed Alembic's historical
    # 32-character default and shrinking the metadata column would be unsafe.
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
