"""Align stored embeddings with the Cloudflare BGE-M3 model.

Revision ID: 0008_embedding_dimensions_1024
Revises: 0007_disable_broken_sources

Historical installations may already have ``opportunity_embeddings`` at this
revision, while truly fresh databases create it later in 0011. Guarding the
resize keeps both upgrade paths valid without creating schema objects here.
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_embedding_dimensions_1024"
down_revision = "0007_disable_broken_sources"
branch_labels = None
depends_on = None


def _embeddings_table_exists() -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text(
                "SELECT EXISTS (SELECT FROM information_schema.tables "
                "WHERE table_schema = current_schema() "
                "AND table_name = 'opportunity_embeddings')"
            )
        ).scalar()
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql" or not _embeddings_table_exists():
        return
    op.execute("DROP INDEX IF EXISTS ix_opportunity_embeddings_vector")
    op.execute(
        """
        ALTER TABLE opportunity_embeddings
        ALTER COLUMN embedding TYPE vector(1024)
        USING (
          embedding::real[] ||
          array_fill(0.0::real, ARRAY[1024 - vector_dims(embedding)])
        )::vector(1024)
        """
    )
    op.execute(
        "CREATE INDEX ix_opportunity_embeddings_vector ON opportunity_embeddings "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql" or not _embeddings_table_exists():
        return
    op.execute("DROP INDEX IF EXISTS ix_opportunity_embeddings_vector")
    op.execute(
        """
        ALTER TABLE opportunity_embeddings
        ALTER COLUMN embedding TYPE vector(64)
        USING subvector(embedding, 1, 64)::vector(64)
        """
    )
    op.execute(
        "CREATE INDEX ix_opportunity_embeddings_vector ON opportunity_embeddings "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
