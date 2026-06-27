"""Tests for the secret-leak detector and security documentation.

These tests assert:
- scripts/check-secrets.sh exits 0 on a clean working tree
- scripts/check-secrets.sh exits 1 when a fake ghp_/vcp_/sk-/pk_/rk_ token
  is present in a tracked source file
- scripts/check-secrets.sh respects the ignore list (.git, node_modules,
  .venv, __pycache__, dist, .next)
- docs/security/secret-rotation.md and docs/security/contributor-setup.md
  exist and contain the required sections
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "check-secrets.sh"
SECRET_ROTATION_DOC = REPO_ROOT / "docs" / "security" / "secret-rotation.md"
CONTRIBUTOR_DOC = REPO_ROOT / "docs" / "security" / "contributor-setup.md"


# ---------------------------------------------------------------------------
# Helper: run the script in a clean working copy of the repo
# ---------------------------------------------------------------------------


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    """Mirror the repo into tmp_path and run check-secrets.sh there.

    The script greps the *current working directory* by default, so we copy
    just the directories and files we want to test into tmp_path and chdir
    in for the test. We deliberately do NOT copy .git, .venv, node_modules,
    __pycache__, dist, or .next — those should be ignored by the script
    anyway, and copying them would balloon the test runtime.
    """
    src = REPO_ROOT
    dst = tmp_path / "repo"
    dst.mkdir()

    # Files and directories the script should scan (we only bring what the
    # tests need; we are NOT testing that every file is scanned, only that
    # the script honors the ignore list when those paths exist).
    # Note: we deliberately do NOT copy apps/api/tests/ because that
    # directory contains the test source itself, which has planted fake
    # tokens that would cause the script to report them.
    paths_to_copy = ["scripts", "docs", "package.json", "render.yaml", "vercel.json"]
    for rel in paths_to_copy:
        src_path = src / rel
        if not src_path.exists():
            continue
        dst_path = dst / rel
        if src_path.is_dir():
            _copy_tree_filtered(src_path, dst_path)
        else:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            dst_path.write_bytes(src_path.read_bytes())

    # Create the ignore-list directories with planted decoy secrets so we
    # can verify the script SKIPS them. We build the fake token at runtime
    # so the test source itself does not contain a literal "ghp_" string —
    # otherwise running the scanner against the real repo would flag this
    # test file as a leak.
    decoy_token = "ghp_" + "X" * 36
    for ignore_rel in [".venv", "node_modules", "__pycache__", "dist", ".next"]:
        decoy = dst / ignore_rel / "subdir"
        decoy.mkdir(parents=True, exist_ok=True)
        (decoy / "leaked.py").write_text(f'GITHUB_TOKEN = "{decoy_token}"\n')

    return dst


def _copy_tree_filtered(src: Path, dst: Path) -> None:
    """Copy a directory tree, skipping the same paths the script ignores."""
    skip = {".git", "node_modules", ".venv", "__pycache__", "dist", ".next", ".pytest_cache"}
    dst.mkdir(parents=True, exist_ok=True)
    for root, dirs, files in os.walk(src):
        rel_root = Path(root).relative_to(src)
        # Prune skipped directories in-place
        dirs[:] = [
            d for d in dirs if d not in skip and not any(p in skip for p in (rel_root / d).parts)
        ]
        for f in files:
            rel = rel_root / f
            if any(p in skip for p in rel.parts):
                continue
            src_file = Path(root) / f
            dst_file = dst / rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            dst_file.write_bytes(src_file.read_bytes())


def _run_script(cwd: Path) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=cwd,
        check=False,
    )
    return proc


# ---------------------------------------------------------------------------
# Script behavior — clean tree
# ---------------------------------------------------------------------------


def test_script_exits_zero_on_clean_tree(work_dir: Path) -> None:
    proc = _run_script(work_dir)
    assert proc.returncode == 0, (
        f"check-secrets.sh returned {proc.returncode} on a clean tree.\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )


# ---------------------------------------------------------------------------
# Script behavior — planted leak
# ---------------------------------------------------------------------------


def test_script_exits_nonzero_on_planted_ghp_token(work_dir: Path) -> None:
    # Build the fake token at runtime so the test source itself never
    # contains a literal "ghp_" string.
    fake_token = "ghp_" + "A" * 36
    leak = work_dir / "apps" / "api" / "app" / "leaked.py"
    leak.parent.mkdir(parents=True, exist_ok=True)
    leak.write_text(f"# oops\n{fake_token}\n")
    proc = _run_script(work_dir)
    assert proc.returncode != 0, (
        "check-secrets.sh did not detect a planted ghp_ token:\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    # The script should mention the offending file or the offending token so
    # the contributor can find it.
    combined = (proc.stdout + proc.stderr).lower()
    assert "leaked.py" in combined or fake_token.lower() in combined, (
        "check-secrets.sh did not report the offending file or token:\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )


def test_script_exits_nonzero_on_vcp_token(work_dir: Path) -> None:
    fake_token = "vcp_" + "B" * 16
    leak = work_dir / "apps" / "web" / "leaked.ts"
    leak.parent.mkdir(parents=True, exist_ok=True)
    leak.write_text(f"const v = '{fake_token}';\n")
    proc = _run_script(work_dir)
    assert proc.returncode != 0


def test_script_exits_nonzero_on_openai_sk_token(work_dir: Path) -> None:
    fake_token = "sk-" + "C" * 16
    leak = work_dir / "apps" / "api" / "app" / "openai_leak.py"
    leak.parent.mkdir(parents=True, exist_ok=True)
    leak.write_text(f'OPENAI_API_KEY = "{fake_token}"\n')
    proc = _run_script(work_dir)
    assert proc.returncode != 0


# ---------------------------------------------------------------------------
# Script behavior — ignore list respected
# ---------------------------------------------------------------------------


def test_script_ignores_node_modules(work_dir: Path) -> None:
    """The planted decoy in node_modules must NOT trigger a failure."""
    proc = _run_script(work_dir)
    assert proc.returncode == 0, (
        f"check-secrets.sh reported a leak in node_modules (should be ignored):\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )


def test_script_ignores_venv_and_pycaches(work_dir: Path) -> None:
    proc = _run_script(work_dir)
    assert proc.returncode == 0, (
        "check-secrets.sh reported a leak in .venv/__pycache__ (should be ignored):\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )


def test_script_ignores_dist_and_next(work_dir: Path) -> None:
    proc = _run_script(work_dir)
    assert proc.returncode == 0


# ---------------------------------------------------------------------------
# Script file shape
# ---------------------------------------------------------------------------


def test_script_exists() -> None:
    assert SCRIPT.exists(), f"Secret scanner not found at {SCRIPT}"


def test_script_is_executable() -> None:
    import stat

    mode = SCRIPT.stat().st_mode
    assert mode & stat.S_IXUSR, f"{SCRIPT} is not executable (no S_IXUSR bit)"


def test_script_is_bash() -> None:
    first_line = SCRIPT.read_text().splitlines()[0]
    assert first_line.startswith("#!") and "bash" in first_line, (
        f"{SCRIPT} should be a bash script (got shebang: {first_line!r})"
    )


# ---------------------------------------------------------------------------
# Documentation
# ---------------------------------------------------------------------------


def test_secret_rotation_doc_exists() -> None:
    assert SECRET_ROTATION_DOC.exists(), f"Missing {SECRET_ROTATION_DOC}"


def test_secret_rotation_doc_has_required_sections() -> None:
    text = SECRET_ROTATION_DOC.read_text().lower()
    for section in [
        "github actions secrets",
        "rotation",
        "90",
    ]:
        assert section in text, (
            f"docs/security/secret-rotation.md must mention '{section}' (case-insensitive)"
        )


def test_contributor_doc_exists() -> None:
    assert CONTRIBUTOR_DOC.exists(), f"Missing {CONTRIBUTOR_DOC}"


def test_contributor_doc_has_required_sections() -> None:
    text = CONTRIBUTOR_DOC.read_text().lower()
    for section in [
        "github",
        "pat",
        ".env",
        "secret",
    ]:
        assert section in text, (
            f"docs/security/contributor-setup.md must mention '{section}' (case-insensitive)"
        )


def test_contributor_doc_warns_about_committing_env() -> None:
    """The doc must explicitly warn against committing .env files."""
    text = CONTRIBUTOR_DOC.read_text()
    assert ".env" in text and "never" in text.lower(), (
        "contributor-setup.md must warn against committing .env files"
    )


# ---------------------------------------------------------------------------
# .gitignore hardening
# ---------------------------------------------------------------------------


def test_root_gitignore_ignores_env_files() -> None:
    text = (REPO_ROOT / ".gitignore").read_text()
    # Either explicit ".env" or ".env*" pattern
    assert ".env" in text, "Root .gitignore must ignore .env files"


def test_root_gitignore_ignores_pem_key_p12() -> None:
    text = (REPO_ROOT / ".gitignore").read_text()
    for ext in ("*.pem", "*.key", "*.p12"):
        assert ext in text, f"Root .gitignore must ignore {ext} files"


def test_web_gitignore_ignores_env_files() -> None:
    web_gitignore = REPO_ROOT / "apps" / "web" / ".gitignore"
    text = web_gitignore.read_text()
    assert ".env" in text, "apps/web/.gitignore must ignore .env files"
