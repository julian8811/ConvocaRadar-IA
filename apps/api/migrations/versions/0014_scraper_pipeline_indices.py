"""Scraper pipeline performance indices.

Revision ID: 0014_scraper_pipeline_indices
Revises: 0013_reclassify_experimental_frequency
"""

from alembic import op

revision = "0014_scraper_pipeline_indices"
down_revision = "0013_reclassify_experimental_frequency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_sources_enabled_tier_last_run",
        "sources",
        ["enabled", "tier", "last_run_at"],
    )
    # Additional sweep-friendly index for due-query (enabled + last_run_at)
    op.create_index(
        "ix_sources_enabled_last_run",
        "sources",
        ["enabled", "last_run_at"],
    )
    # Source runs: keep alias matching spec (existing ix_source_runs_source_created already covers this)
    op.create_index(
        "ix_source_runs_source_id_created_at",
        "source_runs",
        ["source_id", "created_at"],
    )
    op.create_index(
        "ix_opportunities_source_id",
        "opportunities",
        ["source_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_opportunities_source_id", table_name="opportunities")
    op.drop_index("ix_source_runs_source_id_created_at", table_name="source_runs")
    op.drop_index("ix_sources_enabled_last_run", table_name="sources")
    op.drop_index("ix_sources_enabled_tier_last_run", table_name="sources")
