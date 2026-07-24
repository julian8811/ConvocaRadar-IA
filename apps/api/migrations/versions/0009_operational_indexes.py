"""Indexes for source health, task polling and dashboard filters.

Revision ID: 0009_operational_indexes
Revises: 0008_embedding_dimensions_1024
"""

from alembic import op

revision = "0009_operational_indexes"
down_revision = "0008_embedding_dimensions_1024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_source_runs_source_created",
        "source_runs",
        ["source_id", "created_at"],
    )
    op.create_index(
        "ix_tasks_org_status_created",
        "tasks",
        ["organization_id", "status", "created_at"],
    )
    op.create_index(
        "ix_opportunities_org_status_close",
        "opportunities",
        ["organization_id", "status", "close_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_opportunities_org_status_close", table_name="opportunities")
    op.drop_index("ix_tasks_org_status_created", table_name="tasks")
    op.drop_index("ix_source_runs_source_created", table_name="source_runs")
