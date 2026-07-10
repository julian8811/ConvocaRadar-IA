"""Task 1 — Verify obsolete apps/worker/ directory is removed.

The worker was migrated to Celery. The old apps/worker/ directory
contains only __pycache__ and egg-info — dead code that must be
removed along with the root package.json test:worker reference.
"""

from __future__ import annotations

import json
from pathlib import Path


def test_worker_directory_no_longer_exists() -> None:
    """The obsolete apps/worker/ directory must be absent."""
    worker_path = Path(__file__).resolve().parents[3] / "apps" / "worker"
    assert not worker_path.exists(), (
        f"Obsolete apps/worker/ still exists at {worker_path}. "
        "This directory was migrated to Celery and must be removed."
    )


def test_worker_script_removed_from_root_package_json() -> None:
    """Root package.json must not have test:worker script."""
    root = Path(__file__).resolve().parents[3]
    package_json = root / "package.json"
    assert package_json.exists(), f"Root package.json not found at {package_json}"

    data = json.loads(package_json.read_text(encoding="utf-8"))
    test_worker = "test:worker"
    assert test_worker not in data.get("scripts", {}), (
        f"Root package.json still has {test_worker!r} script. "
        "The apps/worker/ directory no longer exists, so this script "
        "must be removed."
    )


def test_root_test_script_no_longer_references_worker() -> None:
    """The root 'test' script must not chain test:worker."""
    root = Path(__file__).resolve().parents[3]
    data = json.loads((root / "package.json").read_text(encoding="utf-8"))
    test_script = data.get("scripts", {}).get("test", "")
    assert "test:worker" not in test_script, (
        f"Root 'test' script still includes 'test:worker': {test_script!r}"
    )
