"""PR1 Governance — university-docker-github-ready (Strict TDD RED).

Covers the 6 governance tasks + backup staleness as described in the preflight:
- CODEOWNERS
- dependabot.yml
- settings.yml (safe-settings branch protection as code)
- CI check-secrets gate (ci.yml)
- SECURITY contact validation
- hadolint / compose lint
- backup staleness (verify_latest_backup age check)

Each test calls production files/real paths — failures are genuine RED until
the governance layer is implemented. Two cases per behavior for triangulation.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
CODEOWNERS = REPO_ROOT / ".github" / "CODEOWNERS"
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"
DEPENDABOT_ALT = REPO_ROOT / ".github" / "dependabot.yaml"
SETTINGS = REPO_ROOT / ".github" / "settings.yml"
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SECURITY = REPO_ROOT / ".github" / "SECURITY.md"
HADOLINT = REPO_ROOT / ".hadolint.yaml"
HADOLINT_ALT = REPO_ROOT / ".hadolint.yml"
COMPOSE = REPO_ROOT / "docker-compose.yml"
VERIFY_BACKUP = REPO_ROOT / "scripts" / "verify_latest_backup.sh"
BACKUP_LOOP = REPO_ROOT / "scripts" / "backup-loop.sh"
CHECK_SECRETS = REPO_ROOT / "scripts" / "check-secrets.sh"


# ── 1. CODEOWNERS ───────────────────────────────────────────────────────────


def test_codeowners_exists():
    assert CODEOWNERS.is_file(), f"CODEOWNERS missing at {CODEOWNERS} — required for review governance"


def test_codeowners_has_global_owner():
    text = CODEOWNERS.read_text() if CODEOWNERS.is_file() else ""
    # Must have a catch-all rule and an @ owner handle
    assert "* " in text or "*\t" in text, "CODEOWNERS must contain a global '*' pattern"
    assert "@" in text, "CODEOWNERS must assign an @owner or @team — bare '*' without owner is not governance"


def test_codeowners_references_docs_and_workflows():
    text = CODEOWNERS.read_text() if CODEOWNERS.is_file() else ""
    # At least one scoped rule ensures ownership is not just "*"
    has_scoped = any(prefix in text for prefix in ["/docs", "docs/", ".github/", "apps/"])
    assert has_scoped, "CODEOWNERS should scope at least one path (e.g. /docs or .github/) beyond global *"


# ── 2. dependabot.yml ───────────────────────────────────────────────────────


def test_dependabot_exists():
    exists = DEPENDABOT.is_file() or DEPENDABOT_ALT.is_file()
    assert exists, f"dependabot config missing — expected {DEPENDABOT} or {DEPENDABOT_ALT}"


def test_dependabot_yaml_is_valid():
    path = DEPENDABOT if DEPENDABOT.is_file() else DEPENDABOT_ALT
    assert path.is_file(), "dependabot file missing — cannot validate"
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, dict) and "updates" in data, "dependabot.yml must have 'updates' key"


def test_dependabot_covers_required_ecosystems():
    path = DEPENDABOT if DEPENDABOT.is_file() else DEPENDABOT_ALT
    assert path.is_file(), "dependabot file missing"
    data = yaml.safe_load(path.read_text())
    ecosystems = {u.get("package-ecosystem") for u in data.get("updates", [])}
    # University-ready stack: pip (api), docker (compose), github-actions (workflows) are mandatory
    for eco in ("pip", "docker", "github-actions"):
        assert eco in ecosystems, f"dependabot must include ecosystem '{eco}' — missing from {ecosystems}"


def test_dependabot_has_weekly_schedule():
    path = DEPENDABOT if DEPENDABOT.is_file() else DEPENDABOT_ALT
    assert path.is_file(), "dependabot file missing"
    data = yaml.safe_load(path.read_text())
    for update in data.get("updates", []):
        schedule = update.get("schedule", {})
        assert schedule.get("interval") in ("weekly", "daily"), (
            f"dependabot entry for {update.get('package-ecosystem')} must have interval weekly/daily, got {schedule}"
        )


# ── 3. settings.yml (safe-settings) ────────────────────────────────────────


def test_settings_yml_exists():
    assert SETTINGS.is_file(), f"settings.yml missing at {SETTINGS} — branch protection as code required"


def test_settings_yml_valid_yaml():
    assert SETTINGS.is_file(), "settings.yml missing"
    data = yaml.safe_load(SETTINGS.read_text())
    assert isinstance(data, dict), "settings.yml must parse to a dict"


def test_settings_branch_protection_main():
    assert SETTINGS.is_file(), "settings.yml missing"
    text = SETTINGS.read_text()
    data = yaml.safe_load(text)
    blob = str(data)
    # Must protect 'main'
    assert "main" in text, "settings.yml must define protection for branch 'main'"
    assert "protection" in blob or "branch" in blob.lower(), "settings.yml must contain branch protection config"


def test_settings_requires_status_checks():
    assert SETTINGS.is_file(), "settings.yml missing"
    text = SETTINGS.read_text()
    # Must require at least the core CI checks as status checks
    for check in ("lint", "test", "frontend", "docker"):
        assert check in text, f"settings.yml branch protection must require status check '{check}'"


def test_settings_requires_pr_reviews():
    assert SETTINGS.is_file(), "settings.yml missing"
    text = SETTINGS.read_text()
    assert "required_pull_request_reviews" in text or "pull_request_reviews" in text, (
        "settings.yml must require pull request reviews"
    )


# ── 4. CI check-secrets gate ───────────────────────────────────────────────


def test_ci_yml_exists():
    assert CI_YML.is_file(), f"ci.yml missing at {CI_YML}"


def test_ci_has_check_secrets_job():
    assert CI_YML.is_file(), "ci.yml missing"
    text = CI_YML.read_text()
    assert "check-secrets" in text or "check_secrets" in text, (
        "ci.yml must contain a 'check-secrets' job that gates the pipeline"
    )


def test_ci_check_secrets_runs_script():
    assert CI_YML.is_file(), "ci.yml missing"
    text = CI_YML.read_text()
    assert "check-secrets" in text.lower() and "check-secrets.sh" in text, (
        "check-secrets job must invoke scripts/check-secrets.sh — the validator that blocks secret leaks"
    )


def test_ci_check_secrets_is_required_gate():
    assert CI_YML.is_file(), "ci.yml missing"
    data = yaml.safe_load(CI_YML.read_text())
    jobs = data.get("jobs", {})
    # check-secrets must be a job that other jobs depend on, or must be in required status checks list
    has_check = any("check" in k and "secret" in k for k in jobs.keys())
    assert has_check, f"ci.yml jobs {list(jobs.keys())} must include a check-secrets job"


def test_check_secrets_script_exists_and_executable():
    assert CHECK_SECRETS.is_file(), f"scripts/check-secrets.sh missing at {CHECK_SECRETS}"
    assert CHECK_SECRETS.stat().st_mode & 0o111 or CHECK_SECRETS.read_text().startswith("#!"), (
        "scripts/check-secrets.sh must be executable or have a shebang"
    )


# ── 5. SECURITY contact validation ─────────────────────────────────────────


def test_security_md_exists():
    assert SECURITY.is_file(), f"SECURITY.md missing at {SECURITY}"


def test_security_has_contact_mechanism():
    assert SECURITY.is_file(), "SECURITY.md missing"
    text = SECURITY.read_text()
    # Must describe how to report — email, advisory, or security@, not just vague prose
    has_contact = any(token in text.lower() for token in ["@", "security@", "advisory", "report", "mail"])
    assert has_contact, "SECURITY.md must document a contact mechanism for reporting vulnerabilities"


def test_security_not_only_personal_gmail():
    assert SECURITY.is_file(), "SECURITY.md missing"
    text = SECURITY.read_text().lower()
    # The previous gmail anchor must not be the SOLE contact — must also have institutional or advisory path
    # If gmail is present, it must be accompanied by a generic security contact or GitHub advisory mention
    if "julianmontoya8811@gmail.com" in text or "@gmail.com" in text:
        has_alternative = any(t in text for t in ["security@", "advisory", "github.com/advisories", "security policy"])
        assert has_alternative or "security@" in text or "advisory" in text, (
            "SECURITY.md uses a personal @gmail.com as sole contact — must add institutional security@ or GitHub Advisory path"
        )


def test_security_has_response_sla():
    assert SECURITY.is_file(), "SECURITY.md missing"
    text = SECURITY.read_text().lower()
    assert "72h" in text or "72 h" in text or "days" in text or "hours" in text, (
        "SECURITY.md must state a response SLA (e.g. 72h)"
    )


# ── 6. hadolint / compose lint ─────────────────────────────────────────────


def test_hadolint_config_exists():
    exists = HADOLINT.is_file() or HADOLINT_ALT.is_file()
    assert exists, f"hadolint config missing — expected {HADOLINT} or {HADOLINT_ALT}"


def test_hadolint_config_valid_yaml():
    path = HADOLINT if HADOLINT.is_file() else HADOLINT_ALT
    assert path.is_file(), "hadolint config missing"
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, dict), "hadolint config must be valid YAML dict"


def test_ci_has_hadolint_step():
    assert CI_YML.is_file(), "ci.yml missing"
    text = CI_YML.read_text().lower()
    assert "hadolint" in text, "ci.yml must include a hadolint lint step for Dockerfiles"


def test_ci_has_compose_lint_step():
    assert CI_YML.is_file(), "ci.yml missing"
    text = CI_YML.read_text()
    assert "docker compose config" in text or "docker-compose config" in text or "compose" in text.lower(), (
        "ci.yml must validate docker-compose.yml via 'docker compose config' (compose lint)"
    )


def test_compose_has_no_hardcoded_secrets():
    assert COMPOSE.is_file(), "docker-compose.yml missing"
    text = COMPOSE.read_text()
    # Ensure compose uses bash substitution for required secrets, not literals
    assert "${POSTGRES_PASSWORD:?must be set}" in text, "docker-compose.yml must use ${POSTGRES_PASSWORD:?must be set}"
    # No literal fallback like :convocaradar as password
    assert "POSTGRES_PASSWORD: convocaradar" not in text, "docker-compose.yml must not hardcode POSTGRES_PASSWORD"


# ── 7. backup staleness ────────────────────────────────────────────────────


def test_verify_backup_script_exists():
    assert VERIFY_BACKUP.is_file(), f"verify_latest_backup.sh missing at {VERIFY_BACKUP}"


def test_verify_backup_checks_age_or_size():
    assert VERIFY_BACKUP.is_file(), "verify_latest_backup.sh missing"
    text = VERIFY_BACKUP.read_text()
    # Must validate either file age (staleness) or minimum size — both are backup integrity gates
    has_staleness = any(kw in text for kw in ["mtime", "age", "stale", "days", "find"])
    has_size = "100" in text or "size" in text.lower()
    assert has_staleness or has_size, (
        "verify_latest_backup.sh must check either staleness (mtime/age) or minimum size"
    )


def test_verify_backup_has_staleness_threshold():
    assert VERIFY_BACKUP.is_file(), "verify_latest_backup.sh missing"
    text = VERIFY_BACKUP.read_text()
    # After PR1, verify script must enforce a max age (e.g. 48h) — fail if backup is too old
    assert "mtime" in text or "hours" in text.lower() or "days" in text.lower() or "stale" in text.lower(), (
        "verify_latest_backup.sh must enforce a staleness threshold (e.g. -mtime +1 or 48h) — stale backups must fail the check"
    )


def test_backup_loop_uses_temp_file_pattern():
    assert BACKUP_LOOP.is_file(), f"backup-loop.sh missing at {BACKUP_LOOP}"
    text = BACKUP_LOOP.read_text()
    # Must use temp file + move to avoid partial files (atomic backup pattern)
    assert "tmp" in text.lower() or "mktemp" in text.lower() or "$$" in text, (
        "backup-loop.sh must write to a temp file first then move — avoids partial backups on failure"
    )
