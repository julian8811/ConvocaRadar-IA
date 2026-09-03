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

Todo el stack está en `docker-compose.yml`. Ver guía paso a paso en
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

### Servidor universitario

```bash
git clone https://github.com/julian8811/ConvocaRadar-IA.git && cd ConvocaRadar-IA
cp .env.example .env && nano .env   # completar 5 secretos + URLs
docker compose build --pull && docker compose up -d
curl -fsS http://localhost:8002/api/v1/health/live
```

Detalle completo: `docs/deploy-universidad.md` + `docs/restore-runbook.md`.

## Local development

```bash
# API + DB + Storage
docker compose up

# Or standalone API
cd apps/api && pip install -e ".[dev]" && uvicorn app.main:app --reload
```
