"""Chain-integrity tests for the Alembic revision graph.

Revision 0008 historically resized an embeddings table that existed on older
installations. Fresh installations create that table later in revision 0011,
so 0008 must explicitly tolerate the table being absent while the graph stays
linear through the current 0016 head. Revision 0013 is the first identifier
that exceeds Alembic's historical VARCHAR(32) metadata default, so it must
widen that column before Alembic records the new revision on PostgreSQL.
"""

from __future__ import annotations

import ast
from pathlib import Path

from alembic.script import ScriptDirectory

API_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = API_DIR / "migrations" / "versions"

EXPECTED_CHAIN = [
    "0001_initial",
    "0002_role_enum",
    "0003_password_changed_at",
    "0004_dom_monitoring",
    "0005_health_score_fields",
    "0006",
    "0007_disable_broken_sources",
    "0008_embedding_dimensions_1024",
    "0009_operational_indexes",
    "0010_source_runs_progress",
    "0011_embedding_bootstrap",
    "0012_fix_sena_allowed_domains",
    "0013_reclassify_experimental_frequency",
    "0014_scraper_pipeline_indices",
    "0015_faculty_match",
    "0016_faculty_match_ivfflat",
]


def _script() -> ScriptDirectory:
    return ScriptDirectory(str(API_DIR / "migrations"))


def _function_body(path: Path, name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.unparse(node)
    raise AssertionError(f"{name}() not found in {path.name}")


def test_migration_graph_has_exactly_one_current_head() -> None:
    assert _script().get_heads() == ["0016_faculty_match_ivfflat"]


def test_chain_is_linear_from_base_to_head() -> None:
    script = _script()
    heads = script.get_heads()
    assert len(heads) == 1, f"expected a single head, got {heads}"
    rev = script.get_revision(heads[0])

    walked: list[str] = []
    while True:
        walked.append(rev.revision)
        down = rev.down_revision
        if down is None:
            break
        assert isinstance(down, str), f"unexpected branch point at {rev.revision}: {down!r}"
        rev = script.get_revision(down)

    walked.reverse()
    assert walked == EXPECTED_CHAIN


def test_0008_skips_resize_when_embeddings_table_is_absent() -> None:
    path = MIGRATIONS_DIR / "0008_embedding_dimensions_1024.py"
    source = path.read_text(encoding="utf-8")
    up = _function_body(path, "upgrade")
    down = _function_body(path, "downgrade")

    assert "information_schema.tables" in source
    assert "_embeddings_table_exists()" in up
    assert "_embeddings_table_exists()" in down
    assert "ALTER TABLE opportunity_embeddings" in up


def test_0011_upgrade_downgrade_are_idempotency_guarded() -> None:
    path = MIGRATIONS_DIR / "0011_embedding_bootstrap.py"
    up = _function_body(path, "upgrade")
    marker_helper = _function_body(path, "_marker_present")
    down = _function_body(path, "downgrade")

    assert "CREATE EXTENSION IF NOT EXISTS vector" in up
    assert "information_schema.tables" in up
    assert "_alembic_0011_created_embeddings" in marker_helper
    assert "information_schema.tables" in marker_helper
    assert "_marker_present(bind)" in down
    assert "DROP TABLE IF EXISTS opportunity_embeddings" in down


def test_0013_widens_alembic_version_column_before_long_revision_id() -> None:
    path = MIGRATIONS_DIR / "0013_reclassify_experimental_frequency.py"
    source = path.read_text(encoding="utf-8")
    up = _function_body(path, "upgrade")

    assert len("0013_reclassify_experimental_frequency") > 32
    assert 'conn.dialect.name == "postgresql"' in up
    assert "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)" in source
