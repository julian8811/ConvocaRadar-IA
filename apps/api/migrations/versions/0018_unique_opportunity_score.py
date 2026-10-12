"""Unique constraint on opportunity_scores (R1 metric fix).

Revision ID: 0018_unique_opportunity_score
Revises: 0017_opportunity_sector

Adds UniqueConstraint (opportunity_id, organization_id) so each
``calculate_score`` call cannot silently fan out duplicate rows that
inflate dashboard KPI counts.

Deploy procedure (server-side, BEFORE applying this migration):
  1. Verify duplicates:
       SELECT opportunity_id, organization_id, COUNT(*)
       FROM opportunity_scores
       GROUP BY opportunity_id, organization_id
       HAVING COUNT(*) > 1;
  2. Keep the newest row per pair, delete the rest:
       DELETE FROM opportunity_scores a USING opportunity_scores b
       WHERE a.id < b.id
         AND a.opportunity_id = b.opportunity_id
         AND a.organization_id = b.organization_id;
  3. Re-run the verification query — must return zero rows.
This migration never deletes data; it only adds the constraint.
"""
from alembic import op

revision = "0018_unique_opportunity_score"
down_revision = "0017_opportunity_sector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_opportunity_scores_opp_org",
        "opportunity_scores",
        ["opportunity_id", "organization_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_opportunity_scores_opp_org",
        "opportunity_scores",
        type_="unique",
    )
