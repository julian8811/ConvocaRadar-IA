"""Add password_changed_at column to users.

Revision ID: 0003_password_changed_at
Revises: 0002_role_enum
Create Date: 2026-06-30

Purpose (PR1 of tier-2-production-readiness):

The ``users`` table gains a ``password_changed_at`` timestamp so we can invalidate
in-flight JWTs on password change. The login and register endpoints embed the
user's current ``password_changed_at`` epoch in the JWT payload; ``get_current_user``
compares the JWT claim against the live row and rejects the token with 401 if the
claim is stale (i.e. the user changed their password after the token was issued).

Schema:
- Column is NULLABLE so existing rows are valid immediately on add.
- Backfill ``created_at`` for existing users — the conservative choice (oldest
  possible ``password_changed_at``) so any token issued before this migration
  remains valid until the user actually changes their password.
- Downgrade drops the column. We do NOT delete the audit log entries written
  by ``scripts/reset_password.py`` (PR1-5) — those are kept.

Idempotency: this migration is safe to re-run by chaining
``alembic upgrade head && alembic downgrade base && alembic upgrade head``.
alembic's revision tracking makes ``upgrade head`` a no-op on the second run.
The downgrade path uses ``op.drop_column`` which is symmetric to ``op.add_column``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0003_password_changed_at"
down_revision = "0002_role_enum"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add the column as nullable so the ADD itself is non-destructive —
    # existing rows get NULL, no default value is required, and the migration
    # succeeds on tables that already contain data.
    op.add_column(
        "users",
        sa.Column("password_changed_at", sa.DateTime(), nullable=True),
    )
    # 2. Backfill existing users. We use COALESCE against created_at so the
    # backfill is deterministic and never produces NULL. For users without a
    # created_at (which would be a data bug — created_at has a server_default
    # in 0001), COALESCE falls back to NOW() so the column is always populated.
    # The WHERE clause is defensive: only touch rows we are backfilling, in case
    # the migration is re-run after a partial backfill on a non-PostgreSQL DB.
    op.execute(
        "UPDATE users SET password_changed_at = COALESCE(created_at, NOW()) "
        "WHERE password_changed_at IS NULL"
    )


def downgrade() -> None:
    op.drop_column("users", "password_changed_at")
