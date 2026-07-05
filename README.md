# ConvocaRadar IA

ConvocaRadar IA is an MVP SaaS for finding, normalizing, scoring, and reporting funding, innovation, research, scholarship, and cooperation opportunities.

## What is included

- **`apps/api`**: FastAPI backend with auth, organizations, profiles, sources, connectors, opportunities, reports, alerts, AI helper endpoints, seed data, and tests.
- **`apps/web`**: Next.js App Router dashboard UI with login, onboarding, opportunities, sources, reports, alerts, settings, and admin views.
- **`docker-compose.yml`**: PostgreSQL with pgvector, MinIO (S3-compatible storage), API, and web.

## Local development

Copy `.env.example` to `.env` for local overrides, then run:

```bash
docker compose up --build
```

This starts PostgreSQL, MinIO, the API, and the frontend.

For lightweight local API development without Docker:

```bash
cd apps/api
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m app.db.seed
.venv/bin/uvicorn app.main:app --reload
```

To apply production-style database migrations:

```bash
cd apps/api
python -m alembic upgrade head
```

Then run the frontend:

```bash
cd apps/web
npm install
npm run dev
```

Local login after seeding:

- Email: `admin@convocaradar.io`
- Password: `ConvocaRadarLocal123!`

## MVP guardrails

- Real opportunities must come from configured sources.
- External web/PDF content is treated as untrusted data.
- Organization boundaries are enforced in API services.
- Scraping uses allowlisted domains, timeout limits, and SSRF checks.

## Source Connectors

All connectors live in `apps/api/app/connectors/` and run inline in the API process (no background worker). They include:

- **`grants-gov`**: Grants.gov public `search2` API connector;
- **`grants-gov-rss`**: Grants.gov public RSS feed connector;
- **`novo-nordisk-grants`**: Novo Nordisk Foundation WordPress grants API with pagination;
- **`horizon-europe-sedia`**: Horizon Europe SEDIA search API for EU funding calls;
- **`minciencias`**: Minciencias Colombia convocatoria listing;
- **`innpulsa`**: iNNpulsa Colombia convocatoria listing;
- **`apc-colombia`**: APC Colombia convocatorias listing;
- **`eu-funding-tenders`**: European Commission calls-for-proposals listing;
- **`wellcome-grants`**, **`gates-foundation-grants`**, **`dfg-grants`**, **`colfuturo-convocatorias`**, **`mincit-innovacion`**: HTML listing sources via the generic HTML connector;
- generic WordPress grants, generic RSS, and generic HTML connectors for custom sources.

Use `POST /api/v1/admin/sources/reseed-defaults` in production to insert new defaults without re-registering the organization.

## Technology Watch Process

Use this monthly checklist to evaluate new funding sources:

1. Discover portals (`/grant`, `/funding`, `/convocatorias`), RSS feeds, and public APIs (`/wp-json/`, OpenAPI docs).
2. Score each candidate (1-5) on technical access, URL stability, structured format, coverage, relevance, legal/ToS, and latency.
3. Classify the connector: RSS seed-only, generic API/HTML, reusable WordPress grants, or dedicated connector.
4. Validate with `POST /api/v1/internal/connectors/probe` before enabling in production.
5. Add to `seed.py`, run reseed, execute a manual source run, and monitor Admin health for 3+ runs.

Discard sources that require login, CAPTCHA, block cloud IPs, or expose only scanned PDFs.

Connector tests use local fixtures and do not require internet access.

## Environment variables

Required variables — the application refuses to start if these are missing or too short:

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | Database connection string | `sqlite:///./convocaradar.db` |
| `JWT_SECRET` | Secret for JWT signing (min 32 chars) | — |
| `INTERNAL_API_KEY` | Internal API auth key (min 32 chars) | — |

LLM configuration — uses Groq via OpenAI-compatible API:

| Variable | Description | Default |
|---|---|---|
| `LLM_PROVIDER` | LLM backend | `openai` |
| `LLM_API_BASE` | OpenAI-compatible API base URL | `https://api.groq.com/openai/v1` |
| `LLM_API_KEY` | API key for the LLM provider | — |
| `CHAT_MODEL` | Chat model name | `llama-3.3-70b-versatile` |
| `EMBEDDING_MODEL` | Embedding model name | `""` |

Email alerts — configured with Resend:

| Variable | Description | Default |
|---|---|---|
| `SMTP_HOST` | SMTP server | `smtp.resend.com` |
| `SMTP_PORT` | SMTP port | `587` |
| `SMTP_USER` | SMTP username | `resend` |
| `SMTP_PASSWORD` | SMTP password or Resend API key | — |
| `SMTP_FROM` | From address | `alerts@convocaradar.local` |
| `SMTP_USE_TLS` | Use TLS for SMTP | `true` |

Storage:

| Variable | Description | Default |
|---|---|---|
| `STORAGE_BACKEND` | Backend type (`local` or `s3`) | `local` |
| `STORAGE_DIR` | Local storage directory | `./storage` |
| `S3_ENDPOINT_URL` | S3-compatible endpoint | `http://localhost:9000` |
| `S3_ACCESS_KEY` | S3 access key | — |
| `S3_SECRET_KEY` | S3 secret key | — |
| `S3_BUCKET` | S3 bucket name | — |
| `S3_REGION` | S3 region | `us-east-1` |

Scraping:

| Variable | Description | Default |
|---|---|---|
| `SCRAPING_EXECUTION_MODE` | Always `inline` (no worker) | `inline` |
| `SCRAPING_USER_AGENT` | User-Agent for HTTP requests | `ConvocaRadarBot/0.1` |
| `SCRAPING_TIMEOUT_SECONDS` | Per-request timeout | `30` |
| `SCRAPING_MAX_SOURCE_SECONDS` | Max time per source run | `90` |
| `SCRAPING_MAX_CONCURRENCY` | Max concurrent scraping requests | `5` |
| `SCRAPING_CLOSING_SOON_DAYS` | Days threshold for "closing soon" | `10` |

Application:

| Variable | Description | Default |
|---|---|---|
| `APP_ENV` | `development` or `production` | `development` |
| `APP_NAME` | Application name | `ConvocaRadar IA` |
| `BACKEND_URL` | Public backend URL | `http://localhost:8000` |
| `FRONTEND_URL` | Public frontend URL | `http://localhost:3000` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT access token TTL | `60` |
| `BOOTSTRAP_SOURCES_ON_STARTUP` | Seed sources on startup | `true` |
| `BOOTSTRAP_SOURCE_KEYS` | Comma-separated source keys to seed | `grants-gov-rss,…` |
| `SENTRY_DSN` | Sentry DSN for error tracking | — |
| `MAX_UPLOAD_BYTES` | Max file upload size | `10000000` |

Frontend:

| Variable | Description | Default |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | API base URL for the frontend | `http://localhost:8000/api/v1` |
| `NEXT_PUBLIC_ENV` | Frontend environment flag | `development` |

## Deployment

### API — Render (single web service)

The API is deployed as a single web service on Render's free tier. See `render.yaml` for the blueprint.

- Docker-based deploy with the `apps/api/Dockerfile`.
- Render free tier spins down after 15 minutes of inactivity. Cold starts take 30–60s.
- **Keep-alive**: a GitHub Actions cron workflow (`keep-alive.yml`) pings `/api/v1/health` every 14 minutes to prevent spin-down.
- The frontend uses a 65-second login timeout to tolerate cold starts and retries `AbortError` connections automatically.
- Sensitive variables (`DATABASE_URL`, `JWT_SECRET`, `INTERNAL_API_KEY`) are synced from GitHub Secrets via the deploy workflow (`deploy.yml`).

### Frontend — Vercel

The Next.js frontend is deployed to Vercel with `vercel-args: --prod`.

### Database — Neon

PostgreSQL with the `pgvector` extension for vector similarity search on embeddings.

### File storage — Cloudflare R2 (or local)

Use `STORAGE_BACKEND=s3` with R2-compatible endpoint, or `STORAGE_BACKEND=local` for single-server setups.

### CI/CD

- `.github/workflows/ci.yml`: runs on push and PR — lints and tests the API and web apps, plus Playwright E2E tests.
- `.github/workflows/deploy.yml`: triggered after CI passes on `main` — deploys API to Render and frontend to Vercel, then runs a post-deploy health check.
- `.github/workflows/keep-alive.yml`: scheduled every 14 minutes — pings the production API health endpoint.

## Testing

### API tests

```bash
cd apps/api
python -m pytest
```

With coverage:

```bash
python -m pytest --cov=app --cov-report=term-missing
```

### Frontend tests

```bash
cd apps/web
npm run test -- --run
```

### E2E tests

```bash
cd apps/web
npx playwright install chromium
npm run test:e2e
```

## Storage

By default, local development stores uploaded documents and generated report artifacts under `STORAGE_DIR`.
Docker Compose sets `STORAGE_BACKEND=s3` and points the API to the bundled MinIO service.
For production, keep the same S3-compatible variables and replace the endpoint/credentials with the target provider.

## Versioning

See [VERSIONING.md](./VERSIONING.md) for the GitHub release flow and semantic versioning rules.
