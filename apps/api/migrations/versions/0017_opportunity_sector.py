"""Cache T4 hybrid sector classification on opportunities (W2).

Revision ID: 0017_opportunity_sector
Revises: 0016_faculty_match_ivfflat
"""
from alembic import op
import sqlalchemy as sa

revision = "0017_opportunity_sector"
down_revision = "0016_faculty_match_ivfflat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("opportunities", sa.Column("sector", sa.String(), nullable=True))
    op.add_column(
        "opportunities", sa.Column("sector_confidence", sa.Float(), nullable=True)
    )
    op.add_column("opportunities", sa.Column("sector_source", sa.String(), nullable=True))
    op.create_index("ix_opportunities_sector", "opportunities", ["sector"])


def downgrade() -> None:
    op.drop_index("ix_opportunities_sector", table_name="opportunities")
    op.drop_column("opportunities", "sector_source")
    op.drop_column("opportunities", "sector_confidence")
    op.drop_column("opportunities", "sector")
