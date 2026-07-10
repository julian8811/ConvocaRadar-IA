"""Add DOM monitoring columns to sources.

Revision ID: 0004_dom_monitoring
Revises: 0003_password_changed_at
Create Date: 2026-07-10

Purpose (Change D — Discovery/Detail Separation + DOM Change Detection):

The ``sources`` table gains four columns to support DOM change detection and
selector health tracking:

- ``dom_hash`` (str, nullable): SHA256 of normalized list-page HTML, used to
  detect structural changes between scrapes.
- ``dom_hash_changed_at`` (datetime, nullable): When the DOM hash last changed.
- ``last_item_count`` (int, nullable): Number of list items found in the last
  successful scrape.
- ``selector_failures`` (int, default=0): Consecutive failures to match any
  configured selector. Auto-pauses the source at >= 3.

All new columns are NULLABLE except ``selector_failures`` which defaults to 0.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0004_dom_monitoring"
down_revision = "0003_password_changed_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("dom_hash", sa.String(), nullable=True))
    op.add_column("sources", sa.Column("dom_hash_changed_at", sa.DateTime(), nullable=True))
    op.add_column("sources", sa.Column("last_item_count", sa.Integer(), nullable=True))
    op.add_column("sources", sa.Column("selector_failures", sa.Integer(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    op.drop_column("sources", "selector_failures")
    op.drop_column("sources", "last_item_count")
    op.drop_column("sources", "dom_hash_changed_at")
    op.drop_column("sources", "dom_hash")
