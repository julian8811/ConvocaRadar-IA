# Secret rotation — ConvocaRadar IA (server stack)

Schedule and procedures for the 5 production secrets in `.env`
(`docker-compose.server.yml`, project `convocaradar`).
Referenced by `scripts/check-secrets.sh`. All commands assume
`COMPOSE='docker compose -p convocaradar --env-file .env -f docker-compose.server.yml'`.

## Schedule

| Secret | Rotate | Effect of rotation |
|---|---|---|
| `JWT_SECRET` | Every 180 days, or on suspected leak | All sessions logged out; in-flight password resets invalidated |
| `INTERNAL_API_KEY` | Every 180 days, or on leak | Machine-to-machine callers must update at the same time |
| `RESET_TOKEN_SECRET` | With `JWT_SECRET` | Pending password-reset links invalidated |
| `POSTGRES_PASSWORD` | Yearly, or on leak | Coordinated DB + app restart (see gotcha below) |
| `MINIO_ROOT_PASSWORD` | Yearly, or on leak | Coordinated MinIO + app restart (see gotcha below) |

After any real leak: rotate IMMEDIATELY, remove the secret from git history
(`git filter-repo` / BFG), and confirm `bash scripts/check-secrets.sh` exits 0.

## Procedure (stateless secrets: JWT / INTERNAL / RESET)

1. Generate: `openssl rand -base64 48` per secret.
2. Write the new value into `.env` (never commit `.env`).
3. Recreate the API consumers: `$COMPOSE up -d api worker web`
   (web bakes `NEXT_PUBLIC_API_URL` at build time, but secrets are runtime —
   no rebuild needed for secret-only changes).
4. Verify: `curl -fsS http://localhost:3001/` and
   `$COMPOSE exec api python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/v1/health/live', timeout=5).status)"`.
5. Log in again (sessions were invalidated) and confirm a sweep task runs.

## Gotcha: data services only read passwords at first init

`POSTGRES_PASSWORD` and `MINIO_ROOT_PASSWORD` are consumed when the
`postgres-data` / `minio-data` volumes are **created**. Changing `.env` alone
on a live volume does nothing — you must change the credential **inside** the
service first, then `.env`, then restart dependents:

- Postgres: `$COMPOSE exec postgres psql -U convocaradar -d convocaradar
  -c "ALTER USER convocaradar WITH PASSWORD '<new>'"` → update `.env` →
  `$COMPOSE up -d api worker backup` → verify `/health/ready`.
- MinIO: rotate via `mc admin user` / server console, then update `.env` →
  `$COMPOSE up -d minio api worker backup` → verify an upload/download round-trip.

Verify each rotation in a maintenance window; never rotate data passwords
without the in-service step above.

## Bootstrap note

`BOOTSTRAP_SOURCES_ON_STARTUP` is pinned to `"false"` in `server.yml`
(api + worker) so boots never trigger scrape sweeps. First-time seeding and
re-seeds run on demand via `POST /api/v1/admin/bootstrap-data`.
