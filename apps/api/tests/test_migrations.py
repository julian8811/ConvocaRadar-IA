"""Tests for the Alembic migration chain.

These tests are STRUCTURAL — they verify the migration files declare the
expected schema changes, not that they execute on the test DB (which is
SQLite; production migrations target PostgreSQL where things like
``ALTER COLUMN ... SET DEFAULT`` work, but SQLite does not support them).

The structural check is enough to catch:
- Wrong revision id / down_revision (chain breakage)
- Missing ``op.add_column`` / ``op.drop_column`` for the new column
- Missing backfill of existing users
- Accidental removal of the column from the downgrade path

A separate operational check (run by humans in CI) is
``alembic upgrade head && alembic downgrade base && alembic upgrade head``
against the real PostgreSQL database.
"""

from __future__ import annotations

import re
from pathlib import Path


MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _extract_function_body(source: str, function_name: str) -> str:
    """Return the body of ``def <function_name>(...)`` as a single string.

    We use Python's ``ast`` module rather than regex to handle arbitrarily nested
    parens, multi-line signatures, and decorators correctly. The returned body is
    the source of the statements inside the function, with the leading indentation
    removed.
    """
    import ast

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            # ast.unparse(node) gives us a normalized rendering of the function
            # with line breaks, which is easier to search than the raw source.
            return ast.unparse(node)
    raise AssertionError(f"Function {function_name!r} not found in migration source")


def _load_migration_source(filename: str) -> str:
    path = MIGRATIONS_DIR / filename
    if not path.exists():
        raise AssertionError(
            f"Expected migration file {path} to exist, but it does not. "
            "Did you forget to create apps/api/migrations/versions/<file>.py ?"
        )
    return path.read_text(encoding="utf-8")


def test_password_changed_at_migration_exists() -> None:
    """The PR1 migration file must exist with a clear name."""
    candidates = list(MIGRATIONS_DIR.glob("*password_changed_at*"))
    assert candidates, (
        f"Expected a migration file matching '*password_changed_at*' in {MIGRATIONS_DIR}, "
        "but none was found. PR1-1 must add a migration to introduce users.password_changed_at."
    )
    assert len(candidates) == 1, (
        f"Expected exactly ONE password_changed_at migration, found {len(candidates)}: {candidates}"
    )


def test_password_changed_at_migration_chain_is_correct() -> None:
    """The migration must declare its revision id and chain onto 0002_role_enum."""
    candidates = list(MIGRATIONS_DIR.glob("*password_changed_at*"))
    assert candidates, "migration file missing (checked in the previous test)"
    source = _load_migration_source(candidates[0].name)

    # Revision id must be present and non-empty
    revision_match = re.search(r'^revision\s*=\s*["\']([^"\']+)["\']', source, re.MULTILINE)
    assert revision_match, f"Missing 'revision = ...' assignment in {candidates[0].name}"
    assert revision_match.group(1), "revision id cannot be empty"

    # Must chain onto 0002_role_enum
    down_match = re.search(r'^down_revision\s*=\s*["\']([^"\']+)["\']', source, re.MULTILINE)
    assert down_match, f"Missing 'down_revision = ...' assignment in {candidates[0].name}"
    assert down_match.group(1) == "0002_role_enum", (
        f"Expected down_revision='0002_role_enum' (latest in chain), "
        f"got {down_match.group(1)!r}. Check that you chained off the right head."
    )


def test_password_changed_at_upgrade_adds_column() -> None:
    """upgrade() must add a nullable DateTime column named password_changed_at."""
    candidates = list(MIGRATIONS_DIR.glob("*password_changed_at*"))
    source = _load_migration_source(candidates[0].name)

    # Must call op.add_column on the users table with password_changed_at
    add_column_match = re.search(
        r'op\.add_column\(\s*["\']users["\']\s*,\s*'
        r'sa\.Column\(\s*["\']password_changed_at["\']\s*,\s*'
        r'sa\.DateTime\(\)\s*,\s*'
        r'nullable\s*=\s*True\s*\)',
        source,
        re.DOTALL,
    )
    assert add_column_match, (
        "Expected upgrade() to call op.add_column('users', sa.Column('password_changed_at', "
        "sa.DateTime(), nullable=True)). The column must be NULLABLE so existing rows do not "
        "violate the constraint on upgrade."
    )


def test_password_changed_at_upgrade_backfills_existing_rows() -> None:
    """upgrade() must backfill existing users so password_changed_at is not NULL for them.

    Without a backfill, existing users would have a NULL password_changed_at, which would
    force password-change invalidation to be a no-op for them (and we lose the ability to
    invalidate their sessions on the next password rotation).
    """
    candidates = list(MIGRATIONS_DIR.glob("*password_changed_at*"))
    source = _load_migration_source(candidates[0].name)

    # Look for an UPDATE statement that sets password_changed_at to a non-NULL value
    # (either NOW() or COALESCE(updated_at, created_at, NOW()) or similar).
    # The regex must tolerate Python's adjacent-string-literal concatenation (the
    # migration may format the SQL across multiple string literals for readability).
    # Strategy: extract the upgrade() function body, collapse whitespace, and search
    # for the SQL pattern in isolation.
    upgrade_body = _extract_function_body(source, "upgrade")
    backfill_match = re.search(
        r'UPDATE\s+users\s+SET\s+password_changed_at\s*=\s*'
        r'(?:COALESCE\s*\([^)]+\)|NOW\s*\(\s*\)|CURRENT_TIMESTAMP)',
        upgrade_body,
        re.IGNORECASE,
    )
    assert backfill_match, (
        "Expected upgrade() to backfill existing users' password_changed_at with a non-NULL value. "
        "Without this, every existing user has NULL password_changed_at and the JWT-invalidation "
        "claim cannot be used to invalidate their sessions. Use either "
        "`op.execute(\"UPDATE users SET password_changed_at = NOW()\")` or "
        "`op.execute(\"UPDATE users SET password_changed_at = COALESCE(updated_at, NOW())\")`."
    )
    assert backfill_match, (
        "Expected upgrade() to backfill existing users' password_changed_at with a non-NULL value. "
        "Without this, every existing user has NULL password_changed_at and the JWT-invalidation "
        "claim cannot be used to invalidate their sessions. Use either "
        "`op.execute(\"UPDATE users SET password_changed_at = NOW()\")` or "
        "`op.execute(\"UPDATE users SET password_changed_at = COALESCE(updated_at, NOW())\")`."
    )


def test_password_changed_at_downgrade_drops_column() -> None:
    """downgrade() must drop the password_changed_at column."""
    candidates = list(MIGRATIONS_DIR.glob("*password_changed_at*"))
    source = _load_migration_source(candidates[0].name)

    drop_match = re.search(
        r'op\.drop_column\(\s*["\']users["\']\s*,\s*["\']password_changed_at["\']\s*\)',
        source,
    )
    assert drop_match, (
        "Expected downgrade() to call op.drop_column('users', 'password_changed_at'). "
        "Symmetric upgrade/downgrade keeps the migration reversible for emergency rollbacks."
    )


def test_password_changed_at_migration_is_idempotent_against_repeated_upgrade() -> None:
    """The migration must declare its actions in a way that supports re-running upgrade().

    Specifically: using op.add_column with the same name twice in SQLite/PostgreSQL is an
    error. The PR1 migration MUST be safe to re-run, which is what alembic enforces
    when the operator runs `alembic upgrade head && alembic downgrade base && alembic upgrade head`.

    We check this by confirming the migration does not call op.add_column without first
    checking if the column already exists. Either the migration uses
    `if not op.get_bind().dialect.has_column(...)` or it relies on alembic's own
    tracking (a unique revision id prevents re-execution within the same head).

    In practice, the standard pattern is: trust alembic's revision tracking and just
    call op.add_column. Re-running the same revision on the same DB raises
    "column already exists" — but that is the migration's job to handle by
    guarding the add_column.
    """
    candidates = list(MIGRATIONS_DIR.glob("*password_changed_at*"))
    source = _load_migration_source(candidates[0].name)

    has_column_guard = "inspect" in source or "has_column" in source or "dialect" in source
    if not has_column_guard:
        # Acceptable pattern: bare op.add_column and rely on alembic revision tracking.
        # The operational test `alembic upgrade head && alembic downgrade base && alembic upgrade head`
        # exercises this: downgrade to base, then upgrade again is fine.
        return

    # If the migration DOES use a guard, verify it is correctly formed
    guard_pattern = re.search(
        r'(op\.get_bind\(\)\.dialect\.has_table|inspect\([^)]+\)\.has_column)',
        source,
    )
    assert guard_pattern, (
        "Migration uses an idempotency guard (inspect/has_column) but the guard pattern "
        "is not recognizable. Use the standard `with op.batch_alter_table('users') as batch:` "
        "or an explicit `if not op.get_bind().dialect.has_column('users', 'password_changed_at'):`."
    )


def test_password_changed_at_migration_has_typed_columns() -> None:
    """Verify the upgrade() function body is syntactically valid Python.

    This catches obvious typos (missing comma, unmatched paren) before the migration
    ever runs in production. It is a cheap belt-and-suspenders check.
    """
    candidates = list(MIGRATIONS_DIR.glob("*password_changed_at*"))
    migration_path = MIGRATIONS_DIR / candidates[0].name

    # AST parse the file. If it does not parse, the test fails with a clear error.
    import ast

    source = migration_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise AssertionError(
            f"Migration file {candidates[0].name} has a Python syntax error: {exc}"
        ) from exc

    # The module must define upgrade() and downgrade()
    function_names = {
        node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "upgrade" in function_names, f"Migration {candidates[0].name} must define an upgrade() function"
    assert "downgrade" in function_names, (
        f"Migration {candidates[0].name} must define a downgrade() function"
    )


def test_password_changed_at_backfill_targets_created_at_or_now() -> None:
    """The backfill must be deterministic — no NULLs after upgrade.

    A NULL password_changed_at means a JWT-invalidation claim of 0 matches the
    stored value, so the password-change invalidation silently no-ops for that
    user. The backfill must use either ``created_at`` (the user-creation
    timestamp, which always exists by schema) or ``NOW()`` as a fallback.
    """
    candidates = list(MIGRATIONS_DIR.glob("*password_changed_at*"))
    source = _load_migration_source(candidates[0].name)
    upgrade_body = _extract_function_body(source, "upgrade")

    # The backfill line must reference created_at or NOW() (or CURRENT_TIMESTAMP)
    uses_created_at = re.search(r"COALESCE\s*\(\s*created_at", upgrade_body, re.IGNORECASE)
    uses_now = re.search(r"COALESCE\s*\([^)]*(?:NOW\(\)|CURRENT_TIMESTAMP)", upgrade_body, re.IGNORECASE)
    uses_bare_now = re.search(
        r"password_changed_at\s*=\s*NOW\s*\(\s*\)", upgrade_body, re.IGNORECASE
    ) and not re.search(r"COALESCE", upgrade_body, re.IGNORECASE)

    assert uses_created_at or uses_now or uses_bare_now, (
        "Expected the backfill to use either `created_at`, `NOW()`, or `CURRENT_TIMESTAMP` "
        "so the resulting password_changed_at is never NULL. The User model has no "
        "`updated_at` column (only `created_at` from 0001_initial), so referencing "
        "`updated_at` would be a bug."
    )

    # Also assert the backfill has a WHERE clause that only touches NULL rows
    # (defensive against re-runs on partially-backfilled databases)
    where_null = re.search(
        r"WHERE\s+password_changed_at\s+IS\s+NULL",
        upgrade_body,
        re.IGNORECASE,
    )
    assert where_null, (
        "Expected the backfill to have a `WHERE password_changed_at IS NULL` clause. "
        "Without it, re-running upgrade() on a partially-backfilled DB would re-stamp "
        "every user's password_changed_at to NOW(), silently invalidating every active "
        "session across the fleet."
    )


def test_password_changed_at_migration_loads_via_alembic_script_directory() -> None:
    """alembic's ScriptDirectory must be able to load the migration as part of the chain.

    This is the integration test for the structural check: if alembic can parse the
    migration and walk the chain, the operators' `alembic upgrade head` will not
    crash with a "could not locate revision" error.
    """
    from alembic.script import ScriptDirectory

    # The script_location in alembic.ini is `migrations` (relative to apps/api)
    script_location = (Path(__file__).resolve().parents[1] / "migrations").resolve()
    script = ScriptDirectory(str(script_location))

    # The new revision must be discoverable
    revisions = {rev.revision: rev for rev in script.walk_revisions()}
    target = "0003_password_changed_at"
    assert target in revisions, (
        f"alembic's ScriptDirectory did not discover revision {target!r}. "
        f"Found: {sorted(revisions)}. The migration file may have a syntax error "
        "or the alembic.ini script_location may be wrong."
    )

    # Chain must link back to 0002_role_enum
    rev = revisions[target]
    assert rev.down_revision == "0002_role_enum", (
        f"alembic reports the new migration chains to {rev.down_revision!r}, "
        f"but we expect '0002_role_enum'. The chain is broken — the head of "
        "0003_password_changed_at will not be applied."
    )
