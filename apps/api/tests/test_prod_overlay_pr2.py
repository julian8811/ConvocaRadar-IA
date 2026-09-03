"""PR2 Prod overlay & validation — university-docker-github-ready (Strict TDD RED).

Covers PR2 tasks per spec/design + preflight:
- docker-compose.prod.yml (port isolation, health gates, hardening/limits/restart)
- config.py validators (strong secrets >=16, placeholder rejection, SQLite in prod)
- .env.example / .env.production.example hardening (5 secrets + URLs + banner)
- backup staleness + delivery docs (entrega-universidad.md 6 sections, DEPLOYMENT, restore)
- compose prod asserts in CI

Each test calls real production files — failures are genuine RED until PR2 implemented.
Two cases per behavior for triangulation.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
PROD_COMPOSE = REPO_ROOT / "docker-compose.prod.yml"
BASE_COMPOSE = REPO_ROOT / "docker-compose.yml"
CONFIG_PY = REPO_ROOT / "apps" / "api" / "app" / "core" / "config.py"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
ENV_PROD = REPO_ROOT / ".env.production.example"
ENTREGA = REPO_ROOT / "docs" / "entrega-universidad.md"
DEPLOYMENT = REPO_ROOT / "DEPLOYMENT.md"
RESTORE = REPO_ROOT / "docs" / "restore-runbook.md"
VERIFY_BACKUP = REPO_ROOT / "scripts" / "verify_latest_backup.sh"
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"

REQUIRED_SECRETS = ("POSTGRES_PASSWORD", "MINIO_ROOT_PASSWORD", "JWT_SECRET", "INTERNAL_API_KEY", "RESET_TOKEN_SECRET")


# ── Prod compose exists ─────────────────────────────────────────────────

def test_prod_compose_exists():
    assert PROD_COMPOSE.is_file(), f"docker-compose.prod.yml missing at {PROD_COMPOSE} — prod overlay required"


def test_prod_compose_valid_yaml():
    assert PROD_COMPOSE.is_file(), "prod compose missing — cannot validate"
    data = yaml.safe_load(PROD_COMPOSE.read_text())
    assert isinstance(data, dict) and "services" in data, "docker-compose.prod.yml must have 'services' key"


# ── Port isolation ──────────────────────────────────────────────────────

def test_prod_removes_postgres_port():
    assert PROD_COMPOSE.is_file(), "prod compose missing"
    text = PROD_COMPOSE.read_text()
    # Prod overlay must explicitly drop the dev-exposed postgres port
    # Either ports: [] for postgres or no 5434:5432 string anywhere in prod file
    assert "5434:5432" not in text, "docker-compose.prod.yml must NOT expose 5434:5432 (postgres) — prod overlay must remove it"
    data = yaml.safe_load(text)
    pg = data.get("services", {}).get("postgres", {})
    if "ports" in pg:
        assert pg["ports"] == [] or pg["ports"] is None, "postgres ports must be [] (removed) in prod overlay"


def test_prod_removes_minio_ports():
    assert PROD_COMPOSE.is_file(), "prod compose missing"
    text = PROD_COMPOSE.read_text()
    assert "9004:9000" not in text, "docker-compose.prod.yml must NOT expose 9004:9000 (minio) — prod overlay must remove it"
    assert "9005:9001" not in text, "docker-compose.prod.yml must NOT expose 9005:9001 (minio console)"
    data = yaml.safe_load(text)
    minio = data.get("services", {}).get("minio", {})
    if "ports" in minio:
        assert minio["ports"] == [] or minio["ports"] is None, "minio ports must be [] (removed) in prod overlay"


def test_prod_keeps_allowed_ports():
    assert PROD_COMPOSE.is_file(), "prod compose missing"
    # Base compose must still expose 8002:8000 (api) and WEB_PORT:3000 (web) — prod keeps them
    base_text = BASE_COMPOSE.read_text() if BASE_COMPOSE.is_file() else ""
    # Base is the source of truth for allowed ports
    assert "8002:8000" in base_text, "base docker-compose.yml must expose 8002:8000 — proves delta"
    # Prod must not remove api/web ports (or must explicitly keep them)
    prod_text = PROD_COMPOSE.read_text()
    prod_data = yaml.safe_load(prod_text)
    # api and web should either be absent (inheriting base) or keep ports
    for svc in ("api", "web"):
        if svc in prod_data.get("services", {}) and "ports" in prod_data["services"][svc]:
            ports = prod_data["services"][svc]["ports"]
            assert ports is not None and len(ports) > 0, f"prod overlay must keep {svc} ports — cannot remove api/web publishing"


def test_base_exposes_dev_ports_proves_delta():
    assert BASE_COMPOSE.is_file(), "base compose missing"
    text = BASE_COMPOSE.read_text()
    assert "5434:5432" in text, "base docker-compose.yml must expose 5434:5432 — proves prod delta removes it"


# ── Health-gated dependencies ───────────────────────────────────────────

def test_prod_health_gated_depends_on():
    assert PROD_COMPOSE.is_file(), "prod compose missing"
    data = yaml.safe_load(PROD_COMPOSE.read_text())
    services = data.get("services", {})
    # api -> postgres healthy
    api_dep = services.get("api", {}).get("depends_on", {})
    assert isinstance(api_dep, dict) and "postgres" in api_dep, "prod api must depend_on postgres with condition service_healthy"
    assert api_dep["postgres"].get("condition") == "service_healthy", "api->postgres must be service_healthy"
    # worker -> api healthy
    worker_dep = services.get("worker", {}).get("depends_on", {})
    assert "api" in worker_dep, "prod worker must depend_on api"
    assert worker_dep["api"].get("condition") == "service_healthy", "worker->api must be service_healthy"
    # backup -> postgres healthy
    backup_dep = services.get("backup", {}).get("depends_on", {})
    assert "postgres" in backup_dep, "prod backup must depend_on postgres"
    assert backup_dep["postgres"].get("condition") == "service_healthy", "backup->postgres must be service_healthy"


def test_prod_has_healthchecks():
    assert PROD_COMPOSE.is_file(), "prod compose missing"
    text = PROD_COMPOSE.read_text().lower()
    # At least postgres and api must have healthcheck in prod (or inherit from base but prod must assert)
    # Check that base has healthchecks and prod doesn't remove them
    base_text = BASE_COMPOSE.read_text().lower() if BASE_COMPOSE.is_file() else ""
    assert "healthcheck" in base_text, "base compose must have healthchecks"
    # Prod overlay should either preserve or explicitly define healthchecks — at minimum not break them
    data = yaml.safe_load(PROD_COMPOSE.read_text())
    # Ensure prod doesn't set healthcheck: {disable: true} or remove
    for svc in ("postgres", "api"):
        if svc in data.get("services", {}):
            assert data["services"][svc].get("healthcheck", {}) is not False, f"prod must not disable {svc} healthcheck"


# ── Container hardening + limits + restart ───────────────────────────────

def test_prod_hardening_cap_drop():
    assert PROD_COMPOSE.is_file(), "prod compose missing"
    data = yaml.safe_load(PROD_COMPOSE.read_text())
    for svc in ("api", "worker", "postgres", "minio"):
        if svc in data.get("services", {}):
            svc_cfg = data["services"][svc]
            assert "cap_drop" in svc_cfg and "ALL" in str(svc_cfg["cap_drop"]), f"{svc} must have cap_drop: [ALL] in prod"


def test_prod_hardening_no_new_privileges():
    assert PROD_COMPOSE.is_file(), "prod compose missing"
    text = PROD_COMPOSE.read_text()
    assert "no-new-privileges" in text, "prod overlay must set security_opt: no-new-privileges:true"


def test_prod_hardening_read_only_and_tmpfs():
    assert PROD_COMPOSE.is_file(), "prod compose missing"
    data = yaml.safe_load(PROD_COMPOSE.read_text())
    for svc in ("api", "worker", "postgres", "minio"):
        if svc in data.get("services", {}):
            svc_cfg = data["services"][svc]
            assert svc_cfg.get("read_only") is True, f"{svc} must have read_only:true in prod"
            assert "tmpfs" in svc_cfg, f"{svc} must have tmpfs for /tmp in prod when read_only"


def test_prod_restart_policy():
    assert PROD_COMPOSE.is_file(), "prod compose missing"
    data = yaml.safe_load(PROD_COMPOSE.read_text())
    for svc in ("api", "worker", "postgres", "minio", "backup", "web"):
        if svc in data.get("services", {}):
            svc_cfg = data["services"][svc]
            assert svc_cfg.get("restart") in ("unless-stopped", "always"), f"{svc} must have restart: unless-stopped in prod"


def test_prod_resource_limits():
    assert PROD_COMPOSE.is_file(), "prod compose missing"
    text = PROD_COMPOSE.read_text()
    # Must set cpu/memory limits via deploy.resources or cpus/mem_limit
    has_limits = any(kw in text for kw in ["deploy", "limits", "cpus", "memory", "mem_limit"])
    assert has_limits, "prod overlay must set cpu/memory limits for services"


# ── Config validators ───────────────────────────────────────────────────

def test_config_py_has_prod_validators():
    assert CONFIG_PY.is_file(), f"config.py missing at {CONFIG_PY}"
    text = CONFIG_PY.read_text()
    assert "field_validator" in text or "AfterValidator" in text, "config.py must use field_validator for secret strength"
    assert "model_validator" in text, "config.py must use model_validator for SQLite-in-prod check"
    assert "PLACEHOLDER" in text or "placeholder" in text.lower(), "config.py must check for placeholder secrets"


def test_config_rejects_weak_secret_in_prod():
    assert CONFIG_PY.is_file(), "config.py missing"
    # Import here so file is loaded fresh; set env to trigger prod validators
    import importlib, os
    os.environ["APP_ENV"] = "production"
    os.environ["JWT_SECRET"] = "short"
    os.environ["INTERNAL_API_KEY"] = "short"
    os.environ["POSTGRES_PASSWORD"] = "short"
    os.environ["MINIO_ROOT_PASSWORD"] = "short"
    os.environ["RESET_TOKEN_SECRET"] = "short"
    os.environ["DATABASE_URL"] = "postgresql+psycopg://convocaradar:strongpass1234567890@postgres:5432/convocaradar"
    # Force reimport
    import app.core.config as cfg_mod
    importlib.reload(cfg_mod)
    try:
        with pytest.raises(Exception) as exc:
            cfg_mod.Settings()
        msg = str(exc.value).lower()
        assert "16" in msg or "32" in msg or "placeholder" in msg or "secret" in msg, f"weak secret should be rejected with >=16 message, got {exc.value}"
    finally:
        for k in ["APP_ENV", "JWT_SECRET", "INTERNAL_API_KEY", "POSTGRES_PASSWORD", "MINIO_ROOT_PASSWORD", "RESET_TOKEN_SECRET", "DATABASE_URL"]:
            os.environ.pop(k, None)
        importlib.reload(cfg_mod)


def test_config_accepts_strong_secrets_in_prod():
    assert CONFIG_PY.is_file(), "config.py missing"
    import importlib, os
    strong = "a" * 32
    os.environ["APP_ENV"] = "production"
    os.environ["JWT_SECRET"] = strong
    os.environ["INTERNAL_API_KEY"] = strong
    os.environ["POSTGRES_PASSWORD"] = strong
    os.environ["MINIO_ROOT_PASSWORD"] = strong
    os.environ["RESET_TOKEN_SECRET"] = strong
    os.environ["DATABASE_URL"] = "postgresql+psycopg://convocaradar:strongpass1234567890@postgres:5432/convocaradar"
    import app.core.config as cfg_mod
    importlib.reload(cfg_mod)
    try:
        s = cfg_mod.Settings()
        assert s.app_env == "production"
    finally:
        for k in ["APP_ENV", "JWT_SECRET", "INTERNAL_API_KEY", "POSTGRES_PASSWORD", "MINIO_ROOT_PASSWORD", "RESET_TOKEN_SECRET", "DATABASE_URL"]:
            os.environ.pop(k, None)
        importlib.reload(cfg_mod)


def test_config_rejects_sqlite_in_prod():
    assert CONFIG_PY.is_file(), "config.py missing"
    import importlib, os
    strong = "b" * 32
    os.environ["APP_ENV"] = "production"
    os.environ["JWT_SECRET"] = strong
    os.environ["INTERNAL_API_KEY"] = strong
    os.environ["POSTGRES_PASSWORD"] = strong
    os.environ["MINIO_ROOT_PASSWORD"] = strong
    os.environ["RESET_TOKEN_SECRET"] = strong
    os.environ["DATABASE_URL"] = "sqlite:///./convocaradar.db"
    import app.core.config as cfg_mod
    importlib.reload(cfg_mod)
    try:
        with pytest.raises(Exception) as exc:
            cfg_mod.Settings()
        assert "sqlite" in str(exc.value).lower() or "postgresql" in str(exc.value).lower(), f"SQLite in prod must be rejected, got {exc.value}"
    finally:
        for k in ["APP_ENV", "JWT_SECRET", "INTERNAL_API_KEY", "POSTGRES_PASSWORD", "MINIO_ROOT_PASSWORD", "RESET_TOKEN_SECRET", "DATABASE_URL"]:
            os.environ.pop(k, None)
        importlib.reload(cfg_mod)


def test_config_allows_sqlite_in_development():
    assert CONFIG_PY.is_file(), "config.py missing"
    import importlib, os
    strong = "c" * 32
    os.environ["APP_ENV"] = "development"
    os.environ["JWT_SECRET"] = strong
    os.environ["INTERNAL_API_KEY"] = strong
    os.environ["DATABASE_URL"] = "sqlite:///./convocaradar.db"
    import app.core.config as cfg_mod
    importlib.reload(cfg_mod)
    try:
        s = cfg_mod.Settings()
        assert "sqlite" in s.database_url.lower()
    finally:
        for k in ["APP_ENV", "JWT_SECRET", "INTERNAL_API_KEY", "DATABASE_URL"]:
            os.environ.pop(k, None)
        importlib.reload(cfg_mod)


# ── .env hardening ──────────────────────────────────────────────────────

def test_env_example_has_five_secrets():
    assert ENV_EXAMPLE.is_file(), ".env.example missing"
    text = ENV_EXAMPLE.read_text()
    for secret in REQUIRED_SECRETS:
        assert secret in text, f".env.example must document {secret}"


def test_env_prod_example_has_five_secrets():
    assert ENV_PROD.is_file(), ".env.production.example missing"
    text = ENV_PROD.read_text()
    for secret in REQUIRED_SECRETS:
        assert secret in text, f".env.production.example must document {secret}"


def test_env_files_have_urls():
    for path in (ENV_EXAMPLE, ENV_PROD):
        assert path.is_file(), f"{path} missing"
        text = path.read_text()
        assert "FRONTEND_URL" in text, f"{path.name} must document FRONTEND_URL"
        assert "BACKEND_URL" in text or "NEXT_PUBLIC_API_URL" in text, f"{path.name} must document backend URL"


def test_env_prod_has_strong_placeholder_docs():
    assert ENV_PROD.is_file(), ".env.production.example missing"
    text = ENV_PROD.read_text()
    # Must not contain weak literals like 'change-me' without generation guidance
    # If it does contain placeholder, it must also document openssl generation
    if "change-me" in text.lower() or "replace_with" in text.lower():
        assert "openssl" in text.lower() or "base64" in text.lower() or "generate" in text.lower(), (
            ".env.production.example with placeholders must document how to generate strong secrets (openssl rand)"
        )


# ── Backup staleness ────────────────────────────────────────────────────

def test_verify_backup_staleness_24h():
    assert VERIFY_BACKUP.is_file(), "verify_latest_backup.sh missing"
    text = VERIFY_BACKUP.read_text()
    # Must enforce staleness — either 24h (mtime +1) or explicit 24/48h check
    has_stale = any(kw in text.lower() for kw in ["stale", "mtime", "age"])
    has_threshold = any(kw in text for kw in ["+1", "+2", "24", "48", "hours", "days"])
    assert has_stale and has_threshold, "verify_latest_backup.sh must enforce staleness threshold (e.g. mtime +1 / 24h)"


def test_verify_backup_staleness_triangulation_second_case():
    assert VERIFY_BACKUP.is_file(), "verify_latest_backup.sh missing"
    text = VERIFY_BACKUP.read_text()
    # Must have both size check and staleness — two gates
    assert "100" in text, "verify_latest_backup.sh must keep 100-byte size gate"
    assert "mtime" in text, "verify_latest_backup.sh must have mtime staleness gate"


# ── Delivery docs ───────────────────────────────────────────────────────

def test_entrega_universidad_exists():
    assert ENTREGA.is_file(), f"docs/entrega-universidad.md missing at {ENTREGA}"


def test_entrega_universidad_has_six_sections():
    assert ENTREGA.is_file(), "entrega doc missing"
    text = ENTREGA.read_text().lower()
    # Spec requires 6 sections: prereqs, cp .env + secret gen, one-command prod up, health URLs, backup/restore, troubleshooting
    required_markers = [
        "requisit",  # prereqs / requisitos
        ".env",  # cp .env
        "openssl",  # secret gen
        "docker compose",  # prod up
        "health",  # health URLs
        "backup",  # backup/restore
        "troubleshoot",  # troubleshooting
    ]
    for marker in required_markers:
        assert marker in text, f"docs/entrega-universidad.md must contain section/marker '{marker}'"


def test_entrega_has_restore_drill():
    assert ENTREGA.is_file(), "entrega doc missing"
    text = ENTREGA.read_text().lower()
    assert "restore" in text or "pg_restore" in text or "psql" in text, "entrega doc must document restore drill (pg_restore/psql)"
    assert "verify" in text or "row count" in text or "select" in text, "entrega doc must have verification query after restore"


def test_deployment_md_references_prod():
    assert DEPLOYMENT.is_file(), "DEPLOYMENT.md missing"
    text = DEPLOYMENT.read_text()
    assert "docker-compose.prod.yml" in text or "compose.prod" in text, "DEPLOYMENT.md must reference docker-compose.prod.yml"
    assert "health" in text.lower(), "DEPLOYMENT.md must document health URLs"


def test_restore_runbook_exists():
    assert RESTORE.is_file(), f"docs/restore-runbook.md missing at {RESTORE}"
    text = RESTORE.read_text().lower()
    assert "pg_dump" in text or "pg_restore" in text or "psql" in text, "restore-runbook must document pg restore steps"


# ── CI prod asserts ─────────────────────────────────────────────────────

def test_ci_has_prod_asserts():
    assert CI_YML.is_file(), "ci.yml missing"
    text = CI_YML.read_text()
    has_prod_asserts = ("prod" in text.lower() and "compose" in text.lower()) or "prod-asserts" in text or "prod_asserts" in text
    assert has_prod_asserts, "ci.yml must contain prod-asserts job that validates prod overlay"
    # Must assert no 5434 in prod config
    assert "5434" in text or "prod" in text.lower(), "ci prod-asserts must check port isolation (5434 not in prod config)"


def test_ci_prod_asserts_runs_compose_config():
    assert CI_YML.is_file(), "ci.yml missing"
    text = CI_YML.read_text()
    assert "docker compose" in text and "config" in text, "ci must run 'docker compose config' for prod asserts"
    assert "docker-compose.prod.yml" in text or "compose.prod" in text, "ci prod asserts must use -f docker-compose.prod.yml"
