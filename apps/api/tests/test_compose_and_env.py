"""Static configuration tests for SEC-1.4 follow-up fixes.

These tests guard two pieces of the SEC-1.4 follow-up:

- C1 (CRITICAL): ``docker-compose.yml`` MUST use the bash substitution
  ``${INTERNAL_API_KEY:?must be set}`` for every required secret it sets in
  the ``environment:`` block, never a literal placeholder. The whole point of
  the substitution is that the shell refuses to interpolate the file when the
  variable is unset — that fail-fast behaviour is broken the moment a literal
  value sneaks in, because ``environment:`` overrides ``env_file:`` in compose.

- W1 (WARNING): ``.env.example`` and ``.env.production.example`` MUST start
  with a SAFETY banner warning operators that the values are placeholders
  only and that the application refuses to start without a real ``JWT_SECRET``
  / ``INTERNAL_API_KEY`` (>=32 chars).

The tests intentionally do not rely on docker / docker compose being
installed — they parse the YAML and assert on raw text only.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

# Repo root (this file lives at apps/api/tests/, so the repo root is
# 4 levels up: tests → api → apps → repo_root).
REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
ENV_PROD_EXAMPLE = REPO_ROOT / ".env.production.example"

# Required secrets enforced by pydantic Field(min_length=32) in
# apps/api/app/core/config.py and apps/worker/worker/config.py.
REQUIRED_SECRETS = ("INTERNAL_API_KEY",)

# bash ${VAR:?message} substitution pattern (mandatory-fail form).
_BASH_SUBST_RE = re.compile(r"\$\{[A-Z_][A-Z0-9_]*:\?[^}]+\}")

# SERVICES that need INTERNAL_API_KEY in their environment: block.
_SERVICES_REQUIRING_INTERNAL_API_KEY = ("api",)

# Banner text that MUST appear at the top of both .env files. The exact
# wording is what the verify report asked for; we match loosely on key
# phrases so a future cosmetic tweak doesn't break the test.
_BANNER_MARKERS = (
    "SAFETY",
    "These are placeholders for local development only",
    "NEVER commit real secrets",
    "NEVER deploy with these values",
    "JWT_SECRET",
    "INTERNAL_API_KEY",
    "at least 32 chars",
    "refuse to start",
)


# ── C1: docker-compose.yml bash substitution ─────────────────────────────────


def test_docker_compose_exists() -> None:
    assert COMPOSE_PATH.is_file(), f"docker-compose.yml missing at {COMPOSE_PATH}"


def test_docker_compose_uses_bash_substitution_for_internal_api_key() -> None:
    """Every service that needs INTERNAL_API_KEY MUST reference it via
    ${INTERNAL_API_KEY:?...} bash substitution. A literal value defeats the
    whole fail-fast intent (environment: overrides env_file: in compose).
    """
    with COMPOSE_PATH.open() as f:
        compose = yaml.safe_load(f)

    services = compose["services"]
    for service in _SERVICES_REQUIRING_INTERNAL_API_KEY:
        assert service in services, f"Service '{service}' missing from docker-compose.yml"
        env_block = services[service].get("environment") or {}
        # docker compose allows either a dict or a list for environment:.
        if isinstance(env_block, list):
            env_dict = {item.split("=", 1)[0]: item.split("=", 1)[1] for item in env_block}
        else:
            env_dict = dict(env_block)

        assert "INTERNAL_API_KEY" in env_dict, (
            f"Service '{service}' has no INTERNAL_API_KEY in environment: — "
            f"this is the field SEC-1.4 was supposed to harden."
        )
        value = env_dict["INTERNAL_API_KEY"]
        # The value MUST be a bash ${VAR:?message} substitution. A literal
        # placeholder (even a 32-char one) overrides env_file: and breaks
        # the "fail fast on missing secret" guarantee.
        assert _BASH_SUBST_RE.match(str(value)), (
            f"Service '{service}': INTERNAL_API_KEY is set to literal "
            f"{value!r} — must use ${{INTERNAL_API_KEY:?must be set}} so the "
            f"shell refuses to start the stack when the operator has not "
            f"provided a real secret."
        )


# ── W1: SAFETY banner at top of .env* files ─────────────────────────────────


@pytest.mark.parametrize(
    "env_path",
    [ENV_EXAMPLE, ENV_PROD_EXAMPLE],
    ids=[".env.example", ".env.production.example"],
)
def test_env_files_have_safety_banner_at_top(env_path: Path) -> None:
    """Both .env files MUST start with a SAFETY banner explaining that the
    values are placeholders for local development and that the application
    refuses to start without a real >=32-char JWT_SECRET / INTERNAL_API_KEY.
    """
    assert env_path.is_file(), f"{env_path} missing"
    text = env_path.read_text()
    # Banner is the FIRST comment block — first 10 non-empty lines must
    # cover the SAFETY markers.
    head_lines = [line for line in text.splitlines()[:10] if line.strip()]
    head_blob = "\n".join(head_lines)
    for marker in _BANNER_MARKERS:
        assert marker in head_blob, (
            f"{env_path.name} is missing SAFETY banner marker {marker!r} in "
            f"its first 10 non-empty lines. Operators opening this file for "
            f"the first time will not get the warning.\n"
            f"Got first 10 lines:\n{head_blob}"
        )
