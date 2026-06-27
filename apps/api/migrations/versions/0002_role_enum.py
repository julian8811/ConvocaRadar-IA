"""Add role enum support with "member" as the default role for new users.

Revision ID: 0002_role_enum
Revises: 0001_initial
Create Date: 2026-06-26
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_role_enum"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Set a server_default so that new rows inserted outside the ORM
    # (e.g. raw SQL, other services) also get "member" by default.
    # Existing rows already have a non-null value ('admin' from the old
    # ORM default), so no backfill is needed.
    op.alter_column("users", "role", server_default="member")


def downgrade() -> None:
    op.alter_column("users", "role", server_default=None)
