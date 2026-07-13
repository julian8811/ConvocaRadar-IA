# Deployment — ConvocaRadar IA

## Architecture

```
Frontend (Vercel) ──→ API (Render) ──→ Database (Neon)
                                        └── PostgreSQL + pgvector
```

- **Frontend**: Vercel Hobby — Next.js App Router
- **API**: Render Web Service — FastAPI + SQLAlchemy
- **Database**: Neon Free — PostgreSQL + pgvector
- **Storage**: Cloudflare R2 or local filesystem

## Required variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string (Neon) |
| `JWT_SECRET` | JWT signing secret (min 32 chars) |
| `INTERNAL_API_KEY` | Internal API key (min 32 chars) |
| `RESET_TOKEN_SECRET` | Password reset token secret (min 32 chars) |

See `.env.example` for all configurable variables.

## Deploy workflow

Deploys run via GitHub Actions (`.github/workflows/deploy.yml`):

1. **CI** runs on push/PR to `main` — lint + test API + test web
2. **Deploy** triggers when CI succeeds on `main`:
   - Render API: triggers redeploy via Render API
   - Vercel: `vercel deploy --prod`

## Local development

```bash
# API + DB + Storage
docker compose up

# Or standalone API
cd apps/api && pip install -e ".[dev]" && uvicorn app.main:app --reload
```
