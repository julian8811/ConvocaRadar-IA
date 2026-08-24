"""Chain-integrity tests for the Alembic revision graph (REQ-MIG-0011-1).

Audit regression: revision 0008 — already applied in production — was edited
in place to bootstrap ``opportunity_embeddings``. Applied revisions must stay
byte-exact; schema evolution lands as NEW revisions chained on top (0011).
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

from alembic.script import ScriptDirectory

API_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = API_DIR.parents[1]
MIGRATIONS_DIR = API_DIR / "migrations" / "versions"
MIGRATIONS_REL = "apps/api/migrations/versions"

EXPECTED_CHAIN = [
    "0001_initial",
    "0002_role_enum",
    "0003_password_changed_at",
    "0004_dom_monitoring",
    "0005_health_score_fields",
    # Historical quirk: this revision's id is the bare "0006", not the
    # filename-derived "0006_connector_config".
    "0006",
    "0007_disable_broken_sources",
    "0008_embedding_dimensions_1024",
    "0009_operational_indexes",
    "0010_source_runs_progress",
    "0011_embedding_bootstrap",
]


def _script() -> ScriptDirectory:
    return ScriptDirectory(str(API_DIR / "migrations"))


def test_migration_graph_has_exactly_one_head_0011() -> None:
    """Single-head scenario: exactly one head, and it is 0011."""
    assert _script().get_heads() == ["0011_embedding_bootstrap"]


def test_chain_is_linear_from_base_to_head() -> None:
    """The full graph is the linear sequence 0001 → 0011 with no branches."""
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


def test_applied_0008_stays_byte_identical_to_committed_blob() -> None:
    """The applied 0008 revision must never be edited in the working tree."""
    rel = f"{MIGRATIONS_REL}/0008_embedding_dimensions_1024.py"
    committed = subprocess.run(
        ["git", "show", f"HEAD:{rel}"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    on_disk = (REPO_ROOT / rel).read_text(encoding="utf-8")
    assert on_disk == committed, (
        "Applied migration 0008 drifted from its committed blob. Schema "
        "evolution belongs in a new revision (0011), not an edit to an "
        "already-applied one."
    )


def test_0011_upgrade_downgrade_are_idempotency_guarded() -> None:
    """0011 must exist-check before creating and gate destructive downgrade
    on its creation marker so it never drops a pre-existing table."""

    def _body(name: str) -> str:
        source = (MIGRATIONS_DIR / "0011_embedding_bootstrap.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return ast.unparse(node)
        raise AssertionError(f"{name}() not found in 0011_embedding_bootstrap.py")

    up = _body("upgrade")
    assert "CREATE EXTENSION IF NOT EXISTS vector" in up
    assert "information_schema.tables" in up

    marker_helper = _body("_marker_present")
    assert "_alembic_0011_created_embeddings" in marker_helper
    assert "information_schema.tables" in marker_helper

    down = _body("downgrade")
    assert "_marker_present(bind)" in down
    assert "DROP TABLE IF EXISTS opportunity_embeddings" in down
