"""Add health score and quality gate columns to sources.

Revision ID: 0005_health_score_fields
Revises: 0004_dom_monitoring
Create Date: 2026-07-10

Purpose (Change C — Health Score & Quality Gate):

The ``sources`` table gains three columns:

- ``tier`` (str, nullable): Strategic, complementary, or experimental.
- ``auto_paused`` (bool, default=False): Auto-paused after 3 empty runs.
- ``consecutive_empty_runs`` (int, default=0): Counter for empty results.

All new columns are NULLABLE except ``auto_paused`` and ``consecutive_empty_runs``
which default to False and 0 respectively.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_health_score_fields"
down_revision = "0004_dom_monitoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("tier", sa.String(), nullable=True))
    op.add_column("sources", sa.Column("auto_paused", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("sources", sa.Column("consecutive_empty_runs", sa.Integer(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    op.drop_column("sources", "consecutive_empty_runs")
    op.drop_column("sources", "auto_paused")
    op.drop_column("sources", "tier")
