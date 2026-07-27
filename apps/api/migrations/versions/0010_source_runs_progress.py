"""Add source_runs.progress column.

Revision ID: 0010_source_runs_progress
Revises: 0009_operational_indexes
"""

from alembic import op
import sqlalchemy as sa

revision = "0010_source_runs_progress"
down_revision = "0009_operational_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("source_runs", sa.Column("progress", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("source_runs", "progress")
