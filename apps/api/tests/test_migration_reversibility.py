"""Task 4 — Functional migration reversibility test.

Runs Alembic migrations against a temporary SQLite database and
verifies that migrations are structurally and functionally reversible.

Key insight: Migration 0002_role_enum uses PostgreSQL-only syntax
(``ALTER COLUMN ... SET DEFAULT``) which SQLite does not support.
The full-chain functional test requires PostgreSQL (available in CI).
We test:
  1. SQLite-compatible chain: 0001_initial → upgrade → downgrade
  2. Structural: every migration file has both upgrade() and downgrade()
"""

from __future__ import annotations

import ast
import os
import shutil
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import inspect

from sqlalchemy import create_engine


def _run_alembic(config_file: str, workdir: str, revision: str) -> None:
    """Run alembic upgrade/downgrade to a specific revision."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(config_file)
    cfg.set_main_option("script_location", os.path.join(workdir, "migrations"))
    cfg.set_main_option("prepend_sys_path", ".")

    if revision.startswith("-") or revision == "base":
        command.downgrade(cfg, revision)
    else:
        command.upgrade(cfg, revision)


@pytest.fixture
def temp_db() -> str:
    """Create a temp SQLite DB, set DATABASE_URL, clear settings cache."""
    from app.core.config import get_settings

    tmpdir = tempfile.mkdtemp(prefix="alembic_test_")
    db_path = os.path.join(tmpdir, "test_migrations.db")
    db_url = f"sqlite:///{db_path}"
    old = os.environ.get("DATABASE_URL", "")
    os.environ["DATABASE_URL"] = db_url
    get_settings.cache_clear()
    try:
        yield db_path
    finally:
        os.environ.pop("DATABASE_URL", None)
        if old:
            os.environ["DATABASE_URL"] = old
        get_settings.cache_clear()
        shutil.rmtree(tmpdir, ignore_errors=True)


def _api_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _table_names(db_url: str) -> set[str]:
    """Return set of table names in the given SQLite database."""
    engine = create_engine(db_url)
    with engine.connect() as conn:
        inspector = inspect(conn)
        return set(inspector.get_table_names())


def test_sqlite_initial_migration_is_reversible(temp_db: str) -> None:
    """0001_initial upgrade + downgrade work on SQLite."""
    api_dir = _api_dir()
    alembic_ini = str(api_dir / "alembic.ini")
    db_url = f"sqlite:///{temp_db}"

    # Upgrade to 0001_initial
    _run_alembic(alembic_ini, str(api_dir), "0001_initial")
    tables_after_upgrade = _table_names(db_url) - {"alembic_version"}
    assert "opportunities" in tables_after_upgrade, (
        f"Expected table 'opportunities' after upgrade, got {tables_after_upgrade}"
    )
    assert "users" in tables_after_upgrade

    # Downgrade to base
    _run_alembic(alembic_ini, str(api_dir), "base")
    tables_after_downgrade = _table_names(db_url) - {"alembic_version"}
    assert len(tables_after_downgrade) == 0, (
        f"Expected zero tables after downgrade (excluding alembic_version), "
        f"got {tables_after_downgrade}"
    )

    # Upgrade again (idempotency check)
    _run_alembic(alembic_ini, str(api_dir), "0001_initial")
    tables_after_reupgrade = _table_names(db_url) - {"alembic_version"}
    assert "opportunities" in tables_after_reupgrade


def test_all_migrations_have_downgrade() -> None:
    """Every migration file must declare a downgrade() function.

    This is the structural reversibility guarantee — it covers ALL
    migration files, including PostgreSQL-specific 0002_role_enum.
    """
    migrations_dir = _api_dir() / "migrations" / "versions"
    migration_files = sorted(migrations_dir.glob("*.py"))

    assert len(migration_files) >= 3, (
        f"Expected >=3 migration files, found {len(migration_files)}"
    )

    for mf in migration_files:
        tree = ast.parse(mf.read_text(encoding="utf-8"))
        func_names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert "upgrade" in func_names, f"{mf.name} missing upgrade()"
        assert "downgrade" in func_names, f"{mf.name} missing downgrade()"


def test_migration_chain_is_unbroken() -> None:
    """Verify the migration chain links correctly (each down_revision
    references an existing revision, and the chain is acyclic).
    """
    from alembic.script import ScriptDirectory

    script_dir = ScriptDirectory(str(_api_dir() / "migrations"))
    revisions = list(script_dir.walk_revisions())
    assert len(revisions) >= 3, f"Expected >=3 revisions, found {len(revisions)}"

    heads = script_dir.get_heads()
    assert len(heads) == 1, (
        f"Expected exactly one head, found {len(heads)}: {heads}. "
        "Multiple heads mean a branch in the chain."
    )

    # Verify every revision links back to an existing one (except base)
    known = {rev.revision for rev in revisions}
    for rev in revisions:
        if rev.down_revision is not None:
            assert rev.down_revision in known, (
                f"Revision {rev.revision} has down_revision {rev.down_revision!r} "
                f"which is not a known revision. Known: {known}"
            )
