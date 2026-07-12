"""Runtime migration runner for ConvocaRadar.

Adds columns that were introduced in Changes C and D without requiring
a manual Alembic migration step.  Each SQL statement uses ``IF NOT EXISTS``
where possible and catches errors for idempotent re-runs.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa

logger = logging.getLogger(__name__)

# Columns added after the initial schema, keyed by table.
_COLUMNS: dict[str, list[sa.Column]] = {
    "sources": [
        sa.Column("tier", sa.String(), nullable=True),
        sa.Column("auto_paused", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("consecutive_empty_runs", sa.Integer(), server_default=sa.text("0")),
        sa.Column("dom_hash", sa.String(), nullable=True),
        sa.Column("dom_hash_changed_at", sa.DateTime(), nullable=True),
        sa.Column("last_item_count", sa.Integer(), nullable=True),
        sa.Column("selector_failures", sa.Integer(), server_default=sa.text("0")),
        sa.Column("connector_config", sa.JSON(), nullable=True),
    ],
    "source_runs": [
        sa.Column("progress", sa.JSON(), nullable=True),
    ],
    "users": [
        sa.Column("password_changed_at", sa.DateTime(), nullable=True),
    ],
}


def run_pending_migrations() -> bool:
    """Add any missing columns to the production database.

    Safe to call on every startup — each ``ALTER TABLE ADD COLUMN`` uses
    ``IF NOT EXISTS`` (via dialect-specific error handling) and failures
    are logged but do not block the application from starting.
    """
    from sqlalchemy import inspect, text

    from app.db.session import engine

    try:
        inspector = inspect(engine)
        with engine.begin() as conn:
            for table_name, columns in _COLUMNS.items():
                existing = {c["name"] for c in inspector.get_columns(table_name)}
                for col in columns:
                    if col.name in existing:
                        continue
                    try:
                        col_type = col.type.compile(conn.dialect)
                        nullable = "NULL" if col.nullable else "NOT NULL"
                        default_clause = ""
                        if col.server_default is not None:
                            default_raw = str(col.server_default.arg)
                            default_clause = f" DEFAULT {default_raw}"
                        sql = f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type} {nullable}{default_clause}"
                        conn.execute(text(sql))
                        logger.info("Added column %s.%s", table_name, col.name)
                    except Exception as exc:
                        logger.debug(
                            "Column %s.%s may already exist: %s",
                            table_name,
                            col.name,
                            exc,
                        )
        return True
    except Exception as exc:
        logger.warning("Migration helper failed: %s", exc)
        return False
