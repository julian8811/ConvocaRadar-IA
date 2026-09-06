#!/usr/bin/env bash
set -euo pipefail

PROJECT_NAME="convocaradar"
COMPOSE_FILE="docker-compose.server.yml"
ENV_FILE=".env"
EXPECTED_WEB_PORT="${EXPECTED_WEB_PORT:-3001}"

ok() { printf 'OK    %s\n' "$*"; }
warn() { printf 'WARN  %s\n' "$*" >&2; }
fail() { printf 'ERROR %s\n' "$*" >&2; exit 1; }

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

printf 'ConvocaRadar IA — server preflight\n'
printf 'Repository: %s\n\n' "$repo_root"

[[ -f "$COMPOSE_FILE" ]] || fail "$COMPOSE_FILE not found"
[[ -f "$ENV_FILE" ]] || fail "$ENV_FILE not found; copy .env.production.example to .env first"

command -v docker >/dev/null 2>&1 || fail "docker is not installed or not in PATH"
docker info >/dev/null 2>&1 || fail "Docker daemon is not reachable by the current user"
docker compose version >/dev/null 2>&1 || fail "docker compose plugin is not available"
ok "Docker and Compose are available"

# Production .env contains secrets. Refuse group/world permissions.
mode="$(stat -c '%a' "$ENV_FILE" 2>/dev/null || true)"
[[ -n "$mode" ]] || fail "cannot read permissions for $ENV_FILE"
perm=$((8#$mode))
if (( (perm & 077) != 0 )); then
  fail "$ENV_FILE permissions are $mode; run: chmod 600 $ENV_FILE"
fi
ok "$ENV_FILE permissions are restricted ($mode)"

get_env() {
  local key="$1"
  awk -v k="$key" '
    $0 ~ "^[[:space:]]*" k "=" {
      sub("^[[:space:]]*" k "=", "")
      sub("\\r$", "")
      print
      exit
    }
  ' "$ENV_FILE"
}

require_value() {
  local key="$1" min_len="${2:-1}" value lower
  value="$(get_env "$key")"
  [[ -n "$value" ]] || fail "$key is missing or empty in $ENV_FILE"
  (( ${#value} >= min_len )) || fail "$key must be at least $min_len characters"
  lower="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')"
  case "$lower" in
    *replace_with*|*replace-with*|*change_me*|*change-me*|*changeme*|*placeholder*)
      fail "$key still contains a placeholder value"
      ;;
  esac
}

app_env="$(get_env APP_ENV)"
[[ "${app_env,,}" == "production" ]] || fail "APP_ENV must be production"
require_value POSTGRES_PASSWORD 16
require_value MINIO_ROOT_PASSWORD 16
require_value JWT_SECRET 32
require_value INTERNAL_API_KEY 32
require_value RESET_TOKEN_SECRET 32
ok "Required production settings are present and non-placeholder"

frontend_url="$(get_env FRONTEND_URL)"
backend_url="$(get_env BACKEND_URL)"
[[ -n "$frontend_url" ]] || fail "FRONTEND_URL is empty"
[[ -n "$backend_url" ]] || fail "BACKEND_URL is empty"
case "${frontend_url,,} ${backend_url,,}" in
  *example.edu.co*) fail "FRONTEND_URL/BACKEND_URL still use example.edu.co" ;;
esac
ok "Public application URLs are configured"

web_port="$(get_env WEB_PORT)"
web_port="${web_port:-$EXPECTED_WEB_PORT}"
[[ "$web_port" =~ ^[0-9]+$ ]] || fail "WEB_PORT must be numeric"
(( web_port >= 1 && web_port <= 65535 )) || fail "WEB_PORT is outside 1..65535"
if [[ "$web_port" != "$EXPECTED_WEB_PORT" ]]; then
  warn "WEB_PORT=$web_port (expected $EXPECTED_WEB_PORT for the university deployment)"
fi

# A running ConvocaRadar deployment may legitimately own the port during an
# update. Any unrelated listener is a collision.
if command -v ss >/dev/null 2>&1 && ss -ltnH "sport = :$web_port" 2>/dev/null | grep -q .; then
  if docker ps --format '{{.Names}} {{.Ports}}' 2>/dev/null | grep -E "^${PROJECT_NAME}-.*127\\.0\\.0\\.1:${web_port}->" >/dev/null; then
    warn "127.0.0.1:$web_port is already owned by the existing $PROJECT_NAME stack"
  else
    fail "port $web_port is already in use by another process/container"
  fi
else
  ok "Host port $web_port is available"
fi

# Validate the effective Compose model without printing expanded secrets.
if ! docker compose \
  -p "$PROJECT_NAME" \
  --env-file "$ENV_FILE" \
  -f "$COMPOSE_FILE" \
  config >/dev/null; then
  fail "Compose configuration is invalid"
fi
ok "docker-compose.server.yml renders successfully"

# Server compose must expose only the web service. Parse JSON with Python while
# sending any expanded configuration directly through the pipe (never a file).
if ! docker compose \
  -p "$PROJECT_NAME" \
  --env-file "$ENV_FILE" \
  -f "$COMPOSE_FILE" \
  config --format json \
  | python3 -c '
import json, sys
cfg = json.load(sys.stdin)
services = cfg["services"]
for name in ("postgres", "minio", "api", "worker", "backup"):
    if services[name].get("ports"):
        raise SystemExit(f"{name} must not publish host ports")
ports = services["web"].get("ports") or []
if len(ports) != 1:
    raise SystemExit("web must publish exactly one host port")
p = ports[0]
if str(p.get("target")) != "3000" or p.get("host_ip") != "127.0.0.1":
    raise SystemExit("web must bind container 3000 to 127.0.0.1 only")
for name in ("api", "worker", "backup", "web"):
    svc = services[name]
    if svc.get("read_only") is not True:
        raise SystemExit(f"{name} must be read_only")
    if "ALL" not in (svc.get("cap_drop") or []):
        raise SystemExit(f"{name} must drop ALL capabilities")
' >/dev/null; then
  fail "Server Compose isolation/hardening assertions failed"
fi
ok "Server networking and hardening assertions passed"

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  printf 'Git SHA: %s\n' "$(git rev-parse --short=12 HEAD)"
  if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    warn "tracked files have local modifications"
  else
    ok "Tracked repository files are clean"
  fi
fi

printf '\nPREFLIGHT=PASS\n'
