# Entrega Universidad — ConvocaRadar IA

Checklist for evaluators to clone, configure, and run the production stack unaided
via `docker compose -f docker-compose.yml -f docker-compose.prod.yml`.

## 1. Requisitos previos

- Ubuntu 22.04+ (VM de la universidad) with Docker Engine ≥ 24 + Compose v2 (`docker compose version`)
- 2 vCPU / 4 GB RAM, 20 GB disk
- Ports 80/443 for reverse proxy (or university-assigned ports) + SSH
- Domain or subdomain (e.g. `convocaradar.universidad.edu.co`) — optional but recommended
- Git installed

## 2. Configuración — copiar .env y generar secretos

```bash
git clone https://github.com/julian8811/ConvocaRadar-IA.git
cd ConvocaRadar-IA

# Start from the production template — never commit .env
cp .env.production.example .env
# Or for local dev: cp .env.example .env

# Generate strong secrets for 5 required values (>=16 chars, not placeholder):
# POSTGRES_PASSWORD / MINIO_ROOT_PASSWORD (>=16), JWT_SECRET / INTERNAL_API_KEY / RESET_TOKEN_SECRET (>=32)
openssl rand -base64 24  # use for POSTGRES_PASSWORD
openssl rand -base64 24  # use for MINIO_ROOT_PASSWORD
openssl rand -base64 48  # use for JWT_SECRET
openssl rand -base64 48  # use for INTERNAL_API_KEY
openssl rand -base64 48  # use for RESET_TOKEN_SECRET

# Edit .env and paste generated values plus URLs:
nano .env
```

Minimum `.env` for university VM (production):

```ini
APP_ENV=production
POSTGRES_PASSWORD=<openssl rand -base64 24>
MINIO_ROOT_PASSWORD=<openssl rand -base64 24>
JWT_SECRET=<openssl rand -base64 48>
INTERNAL_API_KEY=<openssl rand -base64 48>
RESET_TOKEN_SECRET=<openssl rand -base64 48>
DATABASE_URL=postgresql+psycopg://convocaradar:${POSTGRES_PASSWORD}@postgres:5432/convocaradar
FRONTEND_URL=https://convocaradar.universidad.edu.co
BACKEND_URL=https://convocaradar.universidad.edu.co
NEXT_PUBLIC_API_URL=https://convocaradar.universidad.edu.co/api/v1
```

Validate: `bash scripts/check-secrets.sh` must exit 0; `APP_ENV=production` with weak secrets will fail fast via `config.py` validators.

## 3. Levantar producción — un solo comando (prod overlay)

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml build --pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Wait ~90s for health gates: postgres healthy → api healthy → worker/web/backup
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

Production overlay differences (`docker-compose.prod.yml`):
- Removes host ports `5434:5432` (postgres) and `9004:9000`/`9005:9001` (minio) — not exposed
- Keeps `8002:8000` (api) and `${WEB_PORT:-3002}:3000` (web) publishable
- Sets `depends_on: condition: service_healthy` for `api→postgres`, `worker→api`, `backup→postgres`
- Adds `read_only: true` + `tmpfs` (`/tmp`), `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, `restart: unless-stopped`, CPU/memory limits

Verify overlay is applied:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml config | grep -v "5434:5432" && echo "prod port isolation OK"
docker compose -f docker-compose.yml -f docker-compose.prod.yml config | grep -q "cap_drop" && echo "hardening present"
```

## 4. Health URLs y verificación

```bash
curl -fsS http://localhost:8002/api/v1/health/live && echo "API live OK"
curl -fsS http://localhost:8002/api/v1/health/ready && echo "API ready OK (DB + migrations)"
curl -fsS http://localhost:3002/ | head -n 20 && echo "Web OK"

# All services healthy <90s:
docker inspect --format='{{.State.Health.Status}}' $(docker compose ps -q postgres api) 2>/dev/null
```

Reverse proxy (Nginx) example — do not expose 8002/3002 directly:

```nginx
server {
    listen 80;
    server_name convocaradar.universidad.edu.co;
    location /api/ { proxy_pass http://127.0.0.1:8002; }
    location / { proxy_pass http://127.0.0.1:3002; }
}
# certbot --nginx -d convocaradar.universidad.edu.co
```

## 5. Backups y restore drill

Nightly `backup` service runs `scripts/backup-cycle.sh` via `supercronic` at 03:30 UTC (see `scripts/crontab-backup`), retention `BACKUP_RETENTION_DAYS=14`.

```bash
# Verify latest backup is fresh (<24h) and not empty (>100 bytes, gzip + CREATE TABLE):
bash scripts/verify_latest_backup.sh backups
# Or via compose volume:
docker compose exec backup ls -lh /backups
bash scripts/verify_latest_backup.sh $(docker volume inspect convocaradar_backups-data --format '{{.Mountpoint}}')

# Manual backup cycle:
docker compose exec backup sh /scripts/backup-cycle.sh
```

Restore drill (documented in `docs/restore-runbook.md`):

```bash
# List backups
ls -lh backups/convocaradar-*.sql.gz | head
latest=$(ls -t backups/convocaradar-*.sql.gz | head -n1)

# Restore to scratch DB and verify
gzip -dc "$latest" | psql postgresql://convocaradar:${POSTGRES_PASSWORD}@localhost:5432/convocaradar_restore
# Verification query — must return row count >0:
psql postgresql://convocaradar:${POSTGRES_PASSWORD}@localhost:5432/convocaradar_restore -c "SELECT count(*) FROM opportunities;"
psql postgresql://convocaradar:${POSTGRES_PASSWORD}@localhost:5432/convocaradar_restore -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"
```

## 6. Troubleshooting

- `POSTGRES_PASSWORD:?must be set` error → `cp .env.production.example .env` and fill 5 secrets + URLs
- `reset_token_secret must be >=16` or `DATABASE_URL must be PostgreSQL` → running `APP_ENV=production` with SQLite or weak placeholder secrets — generate strong values with `openssl rand -base64 48`
- `docker compose config` shows `5434:5432` in prod → missing `-f docker-compose.prod.yml` overlay — always use both `-f` flags
- `verify_latest_backup.sh` reports `Backup is stale: ... older than 24h` → no backup in last 24h — run `docker compose exec backup sh /scripts/backup-cycle.sh` and check `docker compose logs backup`
- `verify_latest_backup.sh` reports `Backup too small` → `pg_dump` failed (check `PGPASSWORD` bridging in `scripts/backup-loop.sh` and `POSTGRES_PASSWORD` in `.env`)
- Web shows `NEXT_PUBLIC_API_URL` bake error → `NEXT_PUBLIC_API_URL` is baked at `docker compose build web` time — rebuild with `docker compose -f ... build --no-cache web` after changing `.env`
- Health `/ready` fails → postgres not healthy yet — wait 30s and `docker compose logs postgres`, then `docker compose ps`
