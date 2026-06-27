#!/usr/bin/env bash
set -euo pipefail

trigger_render_deploy() {
  local label="$1"
  local hook="${2:-}"
  local api_key="${3:-}"
  local service_id="${4:-}"
  local required="${5:-true}"

  echo "${label}: deploy hook $([ -n "$hook" ] && echo configured || echo not-set)"
  echo "${label}: render api key $([ -n "$api_key" ] && echo configured || echo not-set)"
  echo "${label}: service id ${service_id:-missing}"

  if [ -n "$hook" ]; then
    echo "Triggering ${label} deploy via deploy hook..."
    hook_code="$(curl -sS -o /tmp/render-hook-response.txt -w "%{http_code}" -X POST "$hook" || true)"
    if [ "$hook_code" -ge 200 ] && [ "$hook_code" -lt 300 ]; then
      echo "${label} deploy hook accepted (HTTP ${hook_code})."
      return 0
    fi
    echo "${label} deploy hook failed (HTTP ${hook_code}): $(head -c 300 /tmp/render-hook-response.txt)"
    echo "${label} trying Render API key fallback..."
  fi

  if [ -z "$api_key" ] || [ -z "$service_id" ]; then
    if [ "$required" = "true" ]; then
      echo "${label} deploy failed: no working hook and missing Render API credentials."
      return 1
    fi
    echo "${label} deploy not configured; skipping."
    return 0
  fi

  for payload in '{"clearCache":"clear"}' '{}'; do
    echo "Triggering ${label} deploy via Render API with payload ${payload}..."
    api_code="$(curl -sS -o /tmp/render-api-response.txt -w "%{http_code}" \
      -X POST "https://api.render.com/v1/services/${service_id}/deploys" \
      -H "Authorization: Bearer ${api_key}" \
      -H "Content-Type: application/json" \
      -H "Accept: application/json" \
      -d "$payload" || true)"
    if [ "$api_code" -ge 200 ] && [ "$api_code" -lt 300 ]; then
      echo "${label} Render API deploy accepted (HTTP ${api_code})."
      head -c 500 /tmp/render-api-response.txt || true
      echo
      return 0
    fi
    echo "${label} Render API deploy failed (HTTP ${api_code}): $(head -c 300 /tmp/render-api-response.txt)"
  done

  if [ "$required" = "true" ]; then
    return 1
  fi
  echo "${label} deploy skipped after failures."
  return 0
}

trigger_render_deploy "$@"
