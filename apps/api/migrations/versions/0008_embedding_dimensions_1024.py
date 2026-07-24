"""Align stored embeddings with the Cloudflare BGE-M3 model.

Revision ID: 0008_embedding_dimensions_1024
Revises: 0007_disable_broken_sources
"""

from alembic import op

revision = "0008_embedding_dimensions_1024"
down_revision = "0007_disable_broken_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
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
    if op.get_bind().dialect.name != "postgresql":
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
