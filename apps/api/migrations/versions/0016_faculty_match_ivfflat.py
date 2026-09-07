"""Add IVFFLAT index for faculty profile embeddings when pgvector-backed (W2).

Revision ID: 0016_faculty_match_ivfflat
Revises: 0015_faculty_match
"""
from alembic import op
from sqlalchemy import text

revision = "0016_faculty_match_ivfflat"
down_revision = "0015_faculty_match"
branch_labels = None
depends_on = None


def _embedding_is_vector() -> bool:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return False
    type_name = bind.scalar(
        text(
            """
            SELECT format_type(a.atttypid, a.atttypmod)
            FROM pg_attribute AS a
            JOIN pg_class AS c ON c.oid = a.attrelid
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE c.relname = 'faculty_profiles'
              AND a.attname = 'embedding'
              AND a.attnum > 0
              AND NOT a.attisdropped
              AND n.nspname = current_schema()
            """
        )
    )
    return bool(type_name and str(type_name).lower().startswith("vector"))


def upgrade() -> None:
    if not _embedding_is_vector():
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_faculty_profiles_embedding_ivfflat "
        "ON faculty_profiles USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_faculty_profiles_embedding_ivfflat")
