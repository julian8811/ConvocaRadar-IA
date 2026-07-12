"""add connector_config JSON column to sources table

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("connector_config", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("sources", "connector_config")
