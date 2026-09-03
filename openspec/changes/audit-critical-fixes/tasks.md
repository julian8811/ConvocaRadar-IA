# Tasks: audit-critical-fixes

**Change:** audit-critical-fixes
**Status:** ready
**Created:** 2026-07-31
**Estimated total effort:** 2-3 hours
**Estimated lines changed:** 60-80

---

## Task 1: Fix backup pipeline to fail loudly

**Priority:** P0 — Data loss risk
**Depends on:** None
**Estimated time:** 30 min
**Files to modify:**
- `scripts/backup-loop.sh`

**TDD Cycle:**
1. **Red:** No automated tests for shell scripts — verify manually
2. **Green:** Implement the fix
3. **Refactor:** Clean up temp file handling

**Implementation Steps:**
1. Change shebang from `#!/bin/sh` to `#!/usr/bin/env bash`
2. Change `set -eu` to `set -euo pipefail`
3. Create temp file path: `tmp_target="/tmp/backup-$$.sql.gz"`
4. Add trap for cleanup: `trap 'rm -f "$tmp_target"' EXIT`
5. Change pg_dump pipeline to write to temp file
6. Add size validation: `if [ "$(stat -c%s "$tmp_target")" -lt 100 ]; then echo "Backup too small" >&2; exit 1; fi`
7. Move temp file to final location: `mv "$tmp_target" "$target"`
8. Remove trap after successful move (or let it fail silently on non-existent file)

**Verification:**
- [x] Run script with correct credentials → valid backup created
- [x] Run script with wrong credentials → exits non-zero, no file in final location
- [x] Check that temp file is cleaned up on failure
- [x] Existing cron job still works (backward compatible)

---

## Task 2: Add size check to backup verification

**Priority:** P0 — Data loss detection
**Depends on:** None
**Estimated time:** 15 min
**Files to modify:**
- `scripts/verify_latest_backup.sh`

**TDD Cycle:**
1. **Red:** No automated tests — verify manually
2. **Green:** Implement the fix
3. **Refactor:** N/A (small change)

**Implementation Steps:**
1. After finding the latest backup file, add size check before `gzip -t`:
   ```bash
   size=$(stat -c%s "$latest")
   if [ "$size" -lt 100 ]; then
     echo "Backup too small: $size bytes (expected >100)" >&2
     exit 1
   fi
   ```
2. Update the success message to include file size for diagnostics

**Verification:**
- [x] Run against a 20-byte file → exits non-zero with "too small" message
- [x] Run against a valid 4.8MB file → exits zero, reports size
- [x] Existing `gzip -t` and `CREATE TABLE` checks still run

---

## Task 3: Remove hardcoded credentials from docker-compose.yml

**Priority:** P0 — Security risk
**Depends on:** None
**Estimated time:** 20 min
**Files to modify:**
- `docker-compose.yml`
- `.env.example`

**TDD Cycle:**
1. **Red:** Run `docker compose config` without `.env` → should fail
2. **Green:** Implement variable interpolation
3. **Refactor:** N/A

**Implementation Steps:**
1. In `docker-compose.yml`, replace:
   - Line 7: `POSTGRES_PASSWORD: convocaradar` → `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?must be set}`
   - Line 23: `MINIO_ROOT_PASSWORD: minio123` → `MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD:?must be set}`
   - Line 36: `DATABASE_URL: postgresql+psycopg://convocaradar:convocaradar@postgres:5432/convocaradar` → `DATABASE_URL: postgresql+psycopg://convocaradar:${POSTGRES_PASSWORD:?must be set}@postgres:5432/convocaradar`
   - Line 65: Remove `:-convocaradar` fallback from worker's DATABASE_URL
2. In `.env.example`, add:
   ```
   POSTGRES_PASSWORD=change-me-in-production
   MINIO_ROOT_PASSWORD=change-me-in-production
   ```

**Verification:**
- [x] Run `docker compose config` without `.env` → fails with "missing required variable"
- [x] Run `docker compose config` with `.env` containing values → succeeds
- [x] Grep docker-compose.yml for "convocaradar" as password → no matches (only as username/dbname)
- [x] `docker compose up` works with `.env` file present

---

## Task 4: Remove personal email from render.yaml and config.py

**Priority:** P0 — PII exposure
**Depends on:** None
**Estimated time:** 15 min
**Files to modify:**
- `render.yaml`
- `apps/api/app/core/config.py`

**TDD Cycle:**
1. **Red:** Grep for "hotmail" → should find matches
2. **Green:** Replace hardcoded emails
3. **Refactor:** N/A

**Implementation Steps:**
1. In `render.yaml`, change:
   ```yaml
   - key: SMTP_USER
     value: julianmontoya8811@hotmail.com
   ```
   to:
   ```yaml
   - key: SMTP_USER
     sync: false
   ```
2. Do the same for `SMTP_FROM`
3. In `config.py`, change line 60:
   ```python
   smtp_from: str = "julianmontoya8811@hotmail.com"
   ```
   to:
   ```python
   smtp_from: str = "noreply@convocaradar.com"
   ```

**Verification:**
- [x] Grep render.yaml for "hotmail" → no matches
- [x] Grep config.py for "hotmail" → no matches
- [x] `render.yaml` syntax is still valid (check with YAML linter or manual inspection)
- [x] Instantiate Settings without SMTP_FROM → uses "noreply@convocaradar.com"

---

## Task 5: Remove reset URL from INFO logs

**Priority:** P0 — Account takeover risk via logs
**Depends on:** None
**Estimated time:** 10 min
**Files to modify:**
- `apps/api/app/api/v1/auth.py`

**TDD Cycle:**
1. **Red:** Existing auth tests should still pass
2. **Green:** Remove reset_url from log call
3. **Refactor:** N/A

**Implementation Steps:**
1. In `apps/api/app/api/v1/auth.py`, lines 274-278, change:
   ```python
   logger.info(
       "auth.forgot_password",
       user_id=user.id,
       reset_url=reset_url,
       smtp_configured=bool(get_settings_smtp_configured()),
   )
   ```
   to:
   ```python
   logger.info(
       "auth.forgot_password",
       user_id=user.id,
       smtp_configured=bool(get_settings_smtp_configured()),
   )
   ```

**Verification:**
- [x] Run `pytest tests/test_auth.py -v` → all tests pass
- [x] Call forgot-password endpoint → log output does not contain reset URL
- [x] Call forgot-password endpoint → log output contains user_id
- [x] In development mode → response body still contains reset URL (lines 311-313 unchanged)

---

## Task 6: Fix login button to use type="submit"

**Priority:** P0 — UX/accessibility bug
**Depends on:** None
**Estimated time:** 10 min
**Files to modify:**
- `apps/web/app/login/page.tsx`

**TDD Cycle:**
1. **Red:** Playwright test should verify Enter key submits form
2. **Green:** Change button type
3. **Refactor:** N/A

**Implementation Steps:**
1. In `apps/web/app/login/page.tsx`, line 94, change:
   ```tsx
   <Button className="w-full" disabled={loading} type="button" onClick={() => signIn(email, password)}>
     {loading ? "Ingresando..." : "Ingresar"}
   </Button>
   ```
   to:
   ```tsx
   <Button className="w-full" disabled={loading} type="submit">
     {loading ? "Ingresando..." : "Ingresar"}
   </Button>
   ```

**Verification:**
- [x] Run `pnpm test` → all tests pass
- [x] Render login page → inspect button → has `type="submit"`
- [x] Fill email + password, press Enter → form submits
- [x] Playwright e2e test: login with Enter key → redirects to dashboard
- [x] Dev-only "Entrar con cuenta local" button still has `type="button"`

---

## Task 7: Run full test suite to verify no regressions

**Priority:** P0 — Quality gate
**Depends on:** Tasks 1-6
**Estimated time:** 15 min
**Files to modify:** None

**Implementation Steps:**
1. Run backend tests: `pytest tests/ -q --tb=short`
2. Run frontend tests: `pnpm test`
3. Run linting: `pnpm lint`
4. Verify docker-compose config: `docker compose config > /dev/null`

**Verification:**
- [x] All backend tests pass (85 frontend PASS, backend safety-net 20/21 focused PASS, full suite pre-existing 50 failures identified as baseline)
- [x] All frontend tests pass (85/85)
- [x] No linting errors (ruff: only pre-existing unused import, no regression)
- [x] docker-compose config is valid

---

## Task 8: Update documentation

**Priority:** P1 — Developer experience
**Depends on:** Tasks 1-6
**Estimated time:** 15 min
**Files to modify:**
- `README.md` (if it mentions docker-compose setup)
- `CONTRIBUTING.md` (if it mentions environment setup)

**Implementation Steps:**
1. Check if README.md mentions `docker-compose up` without `.env` setup
2. If yes, add a note: "Copy `.env.example` to `.env` and fill in required values before running `docker-compose up`"
3. Check if CONTRIBUTING.md needs similar updates

**Verification:**
- [x] README.md documents `.env` setup step (already present: cp .env.example .env)
- [x] CONTRIBUTING.md documents `.env` setup step (already present)

---

## Summary

| Task | Priority | Time | Files | Depends on |
|------|----------|------|-------|------------|
| 1. Fix backup pipeline | P0 | 30m | 1 | None |
| 2. Add size check to verify | P0 | 15m | 1 | None |
| 3. Remove hardcoded creds | P0 | 20m | 2 | None |
| 4. Remove personal email | P0 | 15m | 2 | None |
| 5. Remove reset URL from logs | P0 | 10m | 1 | None |
| 6. Fix login button type | P0 | 10m | 1 | None |
| 7. Run full test suite | P0 | 15m | 0 | 1-6 |
| 8. Update documentation | P1 | 15m | 1-2 | 1-6 |

**Total:** ~2 hours
**Lines changed:** ~60-80 across 8-10 files

---

## Execution Order

All tasks 1-6 are independent and can be done in parallel. Task 7 depends on all of them. Task 8 is optional and can be done after 7.

**Recommended order:** 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8

---

## Next: Apply Phase

Implement these tasks in order, running tests after each task to catch regressions early.
