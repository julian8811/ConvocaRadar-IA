"""Add IVFFLAT index for faculty profile embeddings (W2).

Revision ID: 0016_faculty_match_ivfflat
Revises: 0015_faculty_match
"""
from alembic import op

revision = "0016_faculty_match_ivfflat"
down_revision = "0015_faculty_match"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector IVFFLAT on faculty_profiles.embedding for cosine search (only on Postgres)
    # Use try/except to remain compatible with SQLite tests
    try:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    except Exception:
        pass
    try:
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_faculty_profiles_embedding_ivfflat ON faculty_profiles USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10)"
        )
    except Exception:
        # Fallback B-tree or skip on SQLite
        pass


def downgrade() -> None:
    try:
        op.execute("DROP INDEX IF EXISTS ix_faculty_profiles_embedding_ivfflat")
    except Exception:
        pass
