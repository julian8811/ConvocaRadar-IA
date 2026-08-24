"""Bootstrap pgvector and opportunity_embeddings idempotently.

Revision ID: 0011_embedding_bootstrap
Revises: 0010_source_runs_progress

Revision 0008 is already applied in production and assumed the embeddings
table exists. This revision owns creating it when it does not:

- Fresh databases: creates the extension, the ``opportunity_embeddings``
  table and its ivfflat index.
- Databases already past 0008 (table present): ensures the index only and
  records nothing in the marker table.
- A ``_alembic_0011_created_embeddings`` sentinel row marks whether this
  revision created the table, so ``downgrade`` drops only objects it
  actually created.
"""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector as EmbeddingVector

revision = "0011_embedding_bootstrap"
down_revision = "0010_source_runs_progress"
branch_labels = None
depends_on = None

MARKER_TABLE = "_alembic_0011_created_embeddings"
INDEX_NAME = "ix_opportunity_embeddings_vector"


def _marker_present(bind) -> bool:
    return bool(
        bind.execute(
            sa.text(
                "SELECT EXISTS (SELECT FROM information_schema.tables "
                "WHERE table_name = '_alembic_0011_created_embeddings')"
            )
        ).scalar()
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Ensure pgvector extension exists (needed for the vector type).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    table_exists = bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT FROM information_schema.tables "
            "WHERE table_name = 'opportunity_embeddings')"
        )
    ).scalar()

    if not table_exists:
        op.create_table(
            "opportunity_embeddings",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "opportunity_id",
                sa.String(),
                sa.ForeignKey("opportunities.id"),
                unique=True,
                index=True,
                nullable=False,
            ),
            sa.Column(
                "organization_id",
                sa.String(),
                sa.ForeignKey("organizations.id"),
                nullable=True,
                index=True,
            ),
            sa.Column("model_version", sa.String(), server_default="local-hash-embeddings-v2"),
            sa.Column("source_text", sa.Text(), server_default=""),
            sa.Column("embedding", EmbeddingVector(1024), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
        )
        op.execute(
            f"CREATE INDEX {INDEX_NAME} ON opportunity_embeddings "
            "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
        )
        op.execute(f"CREATE TABLE {MARKER_TABLE} (marker boolean PRIMARY KEY)")
        op.execute(f"INSERT INTO {MARKER_TABLE} (marker) VALUES (TRUE)")
    else:
        # Table predates this revision (production at applied-0008):
        # make sure the similarity index exists, touch nothing else.
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {INDEX_NAME} ON opportunity_embeddings "
            "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")

    # Only remove the table this revision created. A pre-existing
    # opportunity_embeddings (production data) must survive the downgrade.
    if _marker_present(bind):
        op.execute(f"DROP TABLE IF EXISTS {MARKER_TABLE}")
        op.execute("DROP TABLE IF EXISTS opportunity_embeddings")
