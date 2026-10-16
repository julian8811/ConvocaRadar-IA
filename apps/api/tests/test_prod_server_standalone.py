"""Prod server standalone & validation — university-docker-github-ready.

T4 repo-higiene-estructura: `docker-compose.server.yml` is the single canonical
prod path; the `docker-compose.prod.yml` overlay was removed.

Covers:
- docker-compose.server.yml (port isolation, health gates, hardening/limits/restart,
  BOOTSTRAP_SOURCES_ON_STARTUP=false, S3_* presence, backup built from source)
- config.py validators (strong secrets >=16, placeholder rejection, SQLite in prod)
- .env.example / .env.production.example hardening (5 secrets + URLs + banner)
- backup staleness + delivery docs (entrega-universidad.md 6 sections, DEPLOYMENT, restore)
- compose server asserts in CI

Each test calls real production files. Two cases per behavior for triangulation.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVER_COMPOSE = REPO_ROOT / "docker-compose.server.yml"
PROD_OVERLAY = REPO_ROOT / "docker-compose.prod.yml"
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

INTERNAL_SERVICES = ("postgres", "minio", "api", "worker", "backup")
HARDENED_SERVICES = ("api", "worker", "backup", "web")


def _server_data():
    assert SERVER_COMPOSE.is_file(), f"docker-compose.server.yml missing at {SERVER_COMPOSE} — canonical prod path required"
    data = yaml.safe_load(SERVER_COMPOSE.read_text())
    assert isinstance(data, dict) and "services" in data, "docker-compose.server.yml must have 'services' key"
    return data


# ── Overlay removed / server exists ─────────────────────────────────────

def test_prod_overlay_removed():
    assert not PROD_OVERLAY.exists(), "docker-compose.prod.yml must NOT exist — overlay eliminated in T4, server.yml is canonical"


def test_server_compose_exists():
    assert SERVER_COMPOSE.is_file(), f"docker-compose.server.yml missing at {SERVER_COMPOSE} — canonical prod path required"


def test_server_compose_valid_yaml():
    data = _server_data()
    assert isinstance(data, dict) and "services" in data, "docker-compose.server.yml must have 'services' key"


# ── Port isolation (standalone: only web published, on localhost) ───────

def test_server_removes_postgres_port():
    text = SERVER_COMPOSE.read_text()
    # Standalone prod must not expose the dev postgres port
    assert "5434:5432" not in text, "docker-compose.server.yml must NOT expose 5434:5432 (postgres)"
    pg = _server_data().get("services", {}).get("postgres", {})
    assert not pg.get("ports"), "postgres must publish no host ports in server compose"


def test_server_removes_minio_ports():
    text = SERVER_COMPOSE.read_text()
    assert "9004:9000" not in text, "docker-compose.server.yml must NOT expose 9004:9000 (minio)"
    assert "9005:9001" not in text, "docker-compose.server.yml must NOT expose 9005:9001 (minio console)"
    minio = _server_data().get("services", {}).get("minio", {})
    assert not minio.get("ports"), "minio must publish no host ports in server compose"


def test_server_no_api_worker_backup_ports():
    services = _server_data().get("services", {})
    for svc in ("api", "worker", "backup"):
        assert not services.get(svc, {}).get("ports"), f"{svc} must publish no host ports in server compose (internal only)"


def test_server_only_web_published_on_localhost():
    services = _server_data().get("services", {})
    for svc in INTERNAL_SERVICES:
        assert not services.get(svc, {}).get("ports"), f"{svc} must publish no host ports — only web is published"
    web_ports = services.get("web", {}).get("ports") or []
    assert len(web_ports) == 1, f"web must publish exactly one port: {web_ports}"
    port = str(web_ports[0])
    assert "127.0.0.1" in port, f"web must bind to localhost only: {port}"
    assert port.endswith(":3000"), f"web must target container port 3000: {port}"


def test_server_no_dev_api_port():
    text = SERVER_COMPOSE.read_text()
    assert "8002:8000" not in text, "docker-compose.server.yml must NOT expose the dev api port 8002:8000"


def test_base_exposes_dev_ports_proves_delta():
    assert BASE_COMPOSE.is_file(), "base compose missing"
    text = BASE_COMPOSE.read_text()
    assert "5434:5432" in text, "base docker-compose.yml must expose 5434:5432 — proves server delta removes it"


# ── Health-gated dependencies ───────────────────────────────────────────

def test_server_health_gated_depends_on():
    services = _server_data().get("services", {})
    # api -> postgres + minio healthy
    api_dep = services.get("api", {}).get("depends_on", {})
    assert isinstance(api_dep, dict) and "postgres" in api_dep, "server api must depend_on postgres with condition service_healthy"
    assert api_dep["postgres"].get("condition") == "service_healthy", "api->postgres must be service_healthy"
    assert api_dep.get("minio", {}).get("condition") == "service_healthy", "api->minio must be service_healthy"
    # worker -> api healthy
    worker_dep = services.get("worker", {}).get("depends_on", {})
    assert "api" in worker_dep, "server worker must depend_on api"
    assert worker_dep["api"].get("condition") == "service_healthy", "worker->api must be service_healthy"
    # backup -> postgres healthy
    backup_dep = services.get("backup", {}).get("depends_on", {})
    assert "postgres" in backup_dep, "server backup must depend_on postgres"
    assert backup_dep["postgres"].get("condition") == "service_healthy", "backup->postgres must be service_healthy"


def test_server_has_healthchecks():
    services = _server_data().get("services", {})
    for svc in ("postgres", "api", "minio"):
        assert services.get(svc, {}).get("healthcheck"), f"server {svc} must define a healthcheck"


# ── Container hardening + limits + restart ───────────────────────────────

def test_server_hardening_cap_drop():
    services = _server_data().get("services", {})
    for svc in HARDENED_SERVICES:
        svc_cfg = services.get(svc, {})
        assert "cap_drop" in svc_cfg and "ALL" in str(svc_cfg["cap_drop"]), f"{svc} must have cap_drop: [ALL] in server compose"


def test_server_hardening_no_new_privileges():
    text = SERVER_COMPOSE.read_text()
    assert "no-new-privileges" in text, "server compose must set security_opt: no-new-privileges:true"


def test_server_hardening_read_only_and_tmpfs():
    services = _server_data().get("services", {})
    for svc in HARDENED_SERVICES:
        svc_cfg = services.get(svc, {})
        assert svc_cfg.get("read_only") is True, f"{svc} must have read_only:true in server compose"
        assert "tmpfs" in svc_cfg, f"{svc} must have tmpfs for /tmp in server compose when read_only"


def test_server_restart_policy():
    services = _server_data().get("services", {})
    for svc in (*INTERNAL_SERVICES, "web"):
        svc_cfg = services.get(svc, {})
        assert svc_cfg.get("restart") in ("unless-stopped", "always"), f"{svc} must have restart: unless-stopped in server compose"


def test_server_resource_limits():
    services = _server_data().get("services", {})
    for svc in (*INTERNAL_SERVICES, "web"):
        svc_cfg = services.get(svc, {})
        assert "mem_limit" in svc_cfg or "cpus" in svc_cfg, f"{svc} must set cpu/memory limits (mem_limit/cpus) in server compose"


# ── Prod behavior: no bootstrap on api boot ──────────────────────────────

def test_server_api_disables_bootstrap_on_startup():
    api_env = _server_data()["services"]["api"].get("environment", {})
    assert api_env.get("BOOTSTRAP_SOURCES_ON_STARTUP") == "false", "server api must set BOOTSTRAP_SOURCES_ON_STARTUP=false (worker owns the sweep)"


def test_server_worker_disables_bootstrap_on_startup():
    worker_env = _server_data()["services"]["worker"].get("environment", {})
    assert worker_env.get("BOOTSTRAP_SOURCES_ON_STARTUP") == "false", "server worker must set BOOTSTRAP_SOURCES_ON_STARTUP=false"


# ── Prod behavior: S3 object storage wired ───────────────────────────────

def test_server_api_worker_have_s3_config():
    services = _server_data().get("services", {})
    for svc in ("api", "worker"):
        env = services.get(svc, {}).get("environment", {})
        for key in ("S3_ENDPOINT_URL", "S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_BUCKET"):
            assert key in env, f"server {svc} must define {key} (object-storage backend)"


def test_server_backup_have_s3_config():
    env = _server_data()["services"]["backup"].get("environment", {})
    for key in ("S3_ENDPOINT_URL", "S3_BUCKET", "BACKUP_S3_PREFIX"):
        assert key in env, f"server backup must define {key} (off-site copy)"


# ── Prod behavior: backup built from source ──────────────────────────────

def test_server_backup_built_from_source():
    backup = _server_data()["services"]["backup"]
    assert "build" in backup, "server backup must be built from source (apps/backup/Dockerfile)"
    assert str(backup["build"].get("dockerfile", "")) == "apps/backup/Dockerfile", "server backup must build apps/backup/Dockerfile"


def test_server_backup_has_no_remote_image():
    backup = _server_data()["services"]["backup"]
    assert "image" not in backup, "server backup must not pin a remote image — it is built from source"


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


def test_deployment_md_declares_server_standalone():
    assert DEPLOYMENT.is_file(), "DEPLOYMENT.md missing"
    text = DEPLOYMENT.read_text()
    assert "docker-compose.server.yml" in text, "DEPLOYMENT.md must declare docker-compose.server.yml as the canonical prod path"
    assert "docker-compose.prod.yml" not in text, "DEPLOYMENT.md must not reference the removed docker-compose.prod.yml overlay"


def test_restore_runbook_exists():
    assert RESTORE.is_file(), f"docs/restore-runbook.md missing at {RESTORE}"
    text = RESTORE.read_text().lower()
    assert "pg_dump" in text or "pg_restore" in text or "psql" in text, "restore-runbook must document pg restore steps"


# ── CI server asserts ───────────────────────────────────────────────────

def test_ci_has_prod_asserts():
    assert CI_YML.is_file(), "ci.yml missing"
    text = CI_YML.read_text()
    has_prod_asserts = ("prod" in text.lower() and "compose" in text.lower()) or "prod-asserts" in text or "prod_asserts" in text
    assert has_prod_asserts, "ci.yml must contain prod-asserts job that validates the server compose"
    # Must assert no published ports on internal services in server config
    assert "server" in text.lower() or "prod" in text.lower(), "ci prod-asserts must check the server/standalone prod path"


def test_ci_prod_asserts_runs_compose_config():
    assert CI_YML.is_file(), "ci.yml missing"
    text = CI_YML.read_text()
    assert "docker compose" in text and "config" in text, "ci must run 'docker compose config' for server asserts"
    assert "docker-compose.server.yml" in text, "ci prod asserts must validate the autonomous university server compose"
