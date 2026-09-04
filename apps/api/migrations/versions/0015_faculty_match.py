"""Faculty match catalog.

Revision ID: 0015_faculty_match
Revises: 0014_scraper_pipeline_indices
"""
from alembic import op
import sqlalchemy as sa

revision = "0015_faculty_match"
down_revision = "0014_scraper_pipeline_indices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "faculties",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("color", sa.String(), nullable=False),
        sa.Column("icon", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
    )
    op.create_index("ix_faculties_key", "faculties", ["key"], unique=True)
    op.create_index("ix_faculties_slug", "faculties", ["slug"], unique=True)

    op.create_table(
        "institutional_axes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
    )
    op.create_index("ix_institutional_axes_key", "institutional_axes", ["key"], unique=True)

    op.create_table(
        "faculty_profiles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("faculty_id", sa.String(), sa.ForeignKey("faculties.id"), nullable=False),
        sa.Column("axis_id", sa.String(), sa.ForeignKey("institutional_axes.id"), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False, server_default="0.35"),
        sa.Column("color", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_faculty_profiles_faculty_id", "faculty_profiles", ["faculty_id"])
    op.create_index("ix_faculty_profiles_axis_id", "faculty_profiles", ["axis_id"])
    op.create_unique_constraint("uq_faculty_axis", "faculty_profiles", ["faculty_id", "axis_id"])

    op.create_table(
        "opportunity_axis_matches",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("opportunity_id", sa.String(), sa.ForeignKey("opportunities.id"), nullable=False),
        sa.Column("faculty_id", sa.String(), sa.ForeignKey("faculties.id"), nullable=False),
        sa.Column("axis_id", sa.String(), sa.ForeignKey("institutional_axes.id"), nullable=False),
        sa.Column("embedding_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("llm_score", sa.Float(), nullable=True),
        sa.Column("final_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("verified_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_opportunity_axis_matches_org", "opportunity_axis_matches", ["organization_id"])
    op.create_index("ix_opportunity_axis_matches_opp", "opportunity_axis_matches", ["opportunity_id"])
    op.create_unique_constraint("uq_org_opp_faculty", "opportunity_axis_matches", ["organization_id", "opportunity_id", "faculty_id"])

    op.add_column("alerts", sa.Column("faculty_id", sa.String(), sa.ForeignKey("faculties.id"), nullable=True))
    op.create_index("ix_alerts_faculty_id", "alerts", ["faculty_id"])


def downgrade() -> None:
    op.drop_index("ix_alerts_faculty_id", table_name="alerts")
    op.drop_column("alerts", "faculty_id")
    op.drop_constraint("uq_org_opp_faculty", "opportunity_axis_matches", type_="unique")
    op.drop_index("ix_opportunity_axis_matches_opp", table_name="opportunity_axis_matches")
    op.drop_index("ix_opportunity_axis_matches_org", table_name="opportunity_axis_matches")
    op.drop_table("opportunity_axis_matches")
    op.drop_constraint("uq_faculty_axis", "faculty_profiles", type_="unique")
    op.drop_index("ix_faculty_profiles_axis_id", table_name="faculty_profiles")
    op.drop_index("ix_faculty_profiles_faculty_id", table_name="faculty_profiles")
    op.drop_table("faculty_profiles")
    op.drop_index("ix_institutional_axes_key", table_name="institutional_axes")
    op.drop_table("institutional_axes")
    op.drop_index("ix_faculties_slug", table_name="faculties")
    op.drop_index("ix_faculties_key", table_name="faculties")
    op.drop_table("faculties")
