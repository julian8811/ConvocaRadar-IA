"""Fix SENA allowed_domains to include senasofiaplus.edu.co variants.

Revision ID: 0012_fix_sena_allowed_domains
Revises: 0011_embedding_bootstrap
"""

from alembic import op
from sqlalchemy import text

revision = "0012_fix_sena_allowed_domains"
down_revision = "0011_embedding_bootstrap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # Add senasofiaplus variants to sena-convocatorias allowed_domains
    # Handle both JSON array encodings (postgres json vs sqlite text)
    conn.execute(
        text(
            """
            UPDATE sources
            SET allowed_domains = :domains,
                updated_at = CURRENT_TIMESTAMP
            WHERE key = :key
            """
        ),
        {
            "key": "sena-convocatorias",
            "domains": '["sena.edu.co", "www.sena.edu.co", "senasofiaplus.edu.co", "oferta.senasofiaplus.edu.co", "www.senasofiaplus.edu.co"]',
        },
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            """
            UPDATE sources
            SET allowed_domains = :domains,
                updated_at = CURRENT_TIMESTAMP
            WHERE key = :key
            """
        ),
        {
            "key": "sena-convocatorias",
            "domains": '["sena.edu.co", "www.sena.edu.co"]',
        },
    )
