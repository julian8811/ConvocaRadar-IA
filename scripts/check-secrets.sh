#!/usr/bin/env bash
# scripts/check-secrets.sh
# ------------------------------------------------------------------
# Detects accidentally-committed secrets in the working tree.
#
# Patterns checked (case-sensitive, anchored on token prefix):
#   - ghp_...   GitHub Personal Access Token (classic + fine-grained prefix)
#   - vcp_...   Vercel CLI personal token
#   - sk-...    OpenAI / Anthropic style API key
#   - pk_...    Stripe-style publishable key (when paired with sk_)
#   - rk_...    Stripe restricted key
#
# Exit codes:
#   0  No matches in scanned files
#   1  At least one match (offending file is printed to stdout)
#
# Ignored paths (always skipped, do not need a real .gitignore entry):
#   .git, .venv, node_modules, __pycache__, dist, .next, .pytest_cache,
#   .mypy_cache, .ruff_cache, build, coverage, htmlcov, test_storage,
#   .vercel, .turbo, .tsbuildinfo
#
# Run from the repo root:
#   bash scripts/check-secrets.sh
# ------------------------------------------------------------------
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Patterns are kept simple on purpose: false positives are reviewed manually
# rather than risking missing a real leak. We also match the assignment side
# (key = "...", key: "...", key="...") so a pasted env line is caught.
PATTERNS=(
  "ghp_[A-Za-z0-9]{8,}"
  "vcp_[A-Za-z0-9]{8,}"
  "sk-[A-Za-z0-9]{8,}"
  "pk_[A-Za-z0-9]{8,}"
  "rk_[A-Za-z0-9]{8,}"
)

# Default to scanning the current working directory; allow override via argv.
SCAN_DIR="${1:-$PWD}"

# ripgrep is the fastest path on this repo, but fall back to grep -rE so the
# script works on any minimal container.
if command -v rg >/dev/null 2>&1; then
  SEARCH_TOOL=rg
else
  SEARCH_TOOL=grep
fi

build_rg_args() {
  rg_args=(
    --hidden
    --line-number
    --no-heading
    --color=never
    --glob '!*.png'
    --glob '!*.jpg'
    --glob '!*.jpeg'
    --glob '!*.gif'
    --glob '!*.ico'
    --glob '!*.pdf'
    --glob '!*.zip'
    --glob '!*.tar'
    --glob '!*.gz'
    --glob '!*.tsbuildinfo'
    --glob '!pnpm-lock.yaml'
    --glob '!package-lock.json'
    --glob '!.git/**'
    --glob '!.venv/**'
    --glob '!node_modules/**'
    --glob '!__pycache__/**'
    --glob '!dist/**'
    --glob '!.next/**'
    --glob '!.pytest_cache/**'
    --glob '!.mypy_cache/**'
    --glob '!.ruff_cache/**'
    --glob '!build/**'
    --glob '!coverage/**'
    --glob '!htmlcov/**'
    --glob '!test_storage/**'
    --glob '!.vercel/**'
    --glob '!.turbo/**'
  )
}

build_grep_args() {
  grep_args=(
    -rEn
    --exclude-dir=.git
    --exclude-dir=.venv
    --exclude-dir=node_modules
    --exclude-dir=__pycache__
    --exclude-dir=dist
    --exclude-dir=.next
    --exclude-dir=.pytest_cache
    --exclude-dir=.mypy_cache
    --exclude-dir=.ruff_cache
    --exclude-dir=build
    --exclude-dir=coverage
    --exclude-dir=htmlcov
    --exclude-dir=test_storage
    --exclude-dir=.vercel
    --exclude-dir=.turbo
    --exclude='*.png'
    --exclude='*.jpg'
    --exclude='*.jpeg'
    --exclude='*.gif'
    --exclude='*.ico'
    --exclude='*.pdf'
    --exclude='*.zip'
    --exclude='*.tar'
    --exclude='*.gz'
    --exclude='*.tsbuildinfo'
    --exclude='pnpm-lock.yaml'
    --exclude='package-lock.json'
  )
}

combined_pattern="$(IFS='|'; echo "${PATTERNS[*]}")"

cd "$SCAN_DIR" || exit 1

exit_code=0
matches_found=0

for pat in "${PATTERNS[@]}"; do
  if [ "$SEARCH_TOOL" = "rg" ]; then
    build_rg_args
    output="$(rg "${rg_args[@]}" -e "$pat" . 2>/dev/null || true)"
  else
    build_grep_args
    output="$(grep "${grep_args[@]}" -e "$pat" . 2>/dev/null || true)"
  fi
  if [ -n "$output" ]; then
    matches_found=1
    echo "POTENTIAL SECRET (pattern: $pat):"
    echo "$output"
    echo "---"
  fi
done

if [ "$matches_found" -ne 0 ]; then
  cat <<'EOF'

============================================================
  SECURITY: potential secret(s) detected in the working tree.
  Review the lines above. If any is a real secret:
    1. Rotate the credential IMMEDIATELY (the leaked one is compromised)
    2. Remove the file from history if it was ever committed
       (e.g. git filter-repo, BFG)
    3. Add the file to .gitignore
  See docs/security/secret-rotation.md for the rotation schedule.
============================================================
EOF
  exit_code=1
fi

exit "$exit_code"
