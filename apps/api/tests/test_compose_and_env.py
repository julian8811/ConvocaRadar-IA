"""Static configuration tests for secret interpolation and operator warnings."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
ENV_PROD_EXAMPLE = REPO_ROOT / ".env.production.example"

_BASH_SUBST_RE = re.compile(r"\$\{[A-Z_][A-Z0-9_]*:\?[^}]+\}")
_SERVICES_REQUIRING_INTERNAL_API_KEY = ("api",)

COMMON_BANNER_MARKERS = ("SAFETY", "JWT_SECRET", "INTERNAL_API_KEY")
BANNER_MARKERS_BY_FILE = {
    ".env.example": (
        "local development only",
        "NEVER commit real secrets",
        "NEVER deploy with these values",
        "at least 32 chars",
        "refuse to start",
    ),
    ".env.production.example": (
        "production template",
        "never commit real secrets",
        "replace every placeholder before deploying",
        "openssl rand",
    ),
}


def test_docker_compose_exists() -> None:
    assert COMPOSE_PATH.is_file(), f"docker-compose.yml missing at {COMPOSE_PATH}"


def test_docker_compose_uses_bash_substitution_for_internal_api_key() -> None:
    with COMPOSE_PATH.open() as f:
        compose = yaml.safe_load(f)

    services = compose["services"]
    for service in _SERVICES_REQUIRING_INTERNAL_API_KEY:
        assert service in services, f"Service '{service}' missing from docker-compose.yml"
        env_block = services[service].get("environment") or {}
        if isinstance(env_block, list):
            env_dict = {item.split("=", 1)[0]: item.split("=", 1)[1] for item in env_block}
        else:
            env_dict = dict(env_block)

        assert "INTERNAL_API_KEY" in env_dict
        value = env_dict["INTERNAL_API_KEY"]
        assert _BASH_SUBST_RE.match(str(value)), (
            f"Service '{service}': INTERNAL_API_KEY must use mandatory shell substitution; "
            f"got {value!r}"
        )


@pytest.mark.parametrize(
    "env_path",
    [ENV_EXAMPLE, ENV_PROD_EXAMPLE],
    ids=[".env.example", ".env.production.example"],
)
def test_env_files_have_safety_banner_at_top(env_path: Path) -> None:
    assert env_path.is_file(), f"{env_path} missing"
    head_blob = "\n".join(
        line for line in env_path.read_text(encoding="utf-8").splitlines()[:14] if line.strip()
    )
    lowered = head_blob.lower()

    for marker in COMMON_BANNER_MARKERS:
        assert marker.lower() in lowered, (
            f"{env_path.name} safety banner is missing {marker!r}.\n{head_blob}"
        )
    for marker in BANNER_MARKERS_BY_FILE[env_path.name]:
        assert marker.lower() in lowered, (
            f"{env_path.name} safety banner is missing {marker!r}.\n{head_blob}"
        )
