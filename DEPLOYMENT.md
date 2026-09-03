# Deployment — ConvocaRadar IA

## Architecture

### Opción A — Cloud (actual)

```
Frontend (Vercel) ──→ API (Render) ──→ Database (Neon)
                                        └── PostgreSQL + pgvector
```

- **Frontend**: Vercel Hobby — Next.js App Router
- **API**: Render Web Service — FastAPI + SQLAlchemy
- **Database**: Neon Free — PostgreSQL + pgvector
- **Storage**: Cloudflare R2 or local filesystem

### Opción B — Servidor universitario (self-hosted, recomendado para entrega)

```
Nginx/Caddy (80/443, TLS) ──→ web:3000  (Next.js)
                          └──→ api:8000  (FastAPI)
                                  ├── postgres:5432 (pgvector/pg16)
                                  ├── minio:9000    (S3)
                                  ├── worker        (scheduler)
                                  └── backup        (pg_dump 03:30 UTC)
```

Todo el stack está en `docker-compose.yml`. Producción usa el overlay `docker-compose.prod.yml` (`docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`) que elimina los puertos 5434/9004, añade `depends_on: service_healthy`, `read_only`/`cap_drop`/`no-new-privileges`/limits/`restart` y valida secretos vía `config.py`. Ver guía paso a paso en
**`docs/deploy-universidad.md`**.

## Required variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string (Neon o compose) |
| `POSTGRES_PASSWORD` | Password de Postgres (compose) |
| `MINIO_ROOT_PASSWORD` | Password de MinIO (compose) |
| `JWT_SECRET` | JWT signing secret (min 32 chars) |
| `INTERNAL_API_KEY` | Internal API key (min 32 chars) |
| `RESET_TOKEN_SECRET` | Password reset token secret (min 32 chars) |

See `.env.example` for all configurable variables and `.env.production.example` for producción cloud.

## Deploy workflow

### Cloud (Vercel + Render)

Deploys run via GitHub Actions (`.github/workflows/deploy.yml`):

1. **CI** runs on push/PR to `main` — lint + test API + test web
2. **Deploy** triggers when CI succeeds on `main`:
   - Render API: triggers redeploy via Render API
   - Vercel: `vercel deploy --prod`

### Servidor universitario (prod overlay — entrega)

```bash
git clone https://github.com/julian8811/ConvocaRadar-IA.git && cd ConvocaRadar-IA
cp .env.production.example .env && nano .env   # completar 5 secretos + FRONTEND_URL/BACKEND_URL
# Generate secrets: openssl rand -base64 24 (POSTGRES/MINIO) y openssl rand -base64 48 (JWT/INTERNAL/RESET)
docker compose -f docker-compose.yml -f docker-compose.prod.yml build --pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
curl -fsS http://localhost:8002/api/v1/health/live   # health live
curl -fsS http://localhost:8002/api/v1/health/ready  # health ready (DB + migrations)
```

Detalle completo: `docs/entrega-universidad.md` (6 secciones: requisitos, .env + secretos, prod up, health URLs, backup/restore, troubleshooting) + `docs/restore-runbook.md` + `docs/deploy-universidad.md`.

## Local development

```bash
# API + DB + Storage
docker compose up

# Or standalone API
cd apps/api && pip install -e ".[dev]" && uvicorn app.main:app --reload
```
