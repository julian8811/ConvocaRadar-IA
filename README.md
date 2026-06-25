# ConvocaRadar IA

ConvocaRadar IA is an MVP SaaS for finding, normalizing, scoring, and reporting funding, innovation, research, scholarship, and cooperation opportunities.

## What is included

- `apps/api`: FastAPI backend with auth, organizations, profiles, sources, opportunities, reports, alerts, AI helper endpoints, seed data, and tests.
- `apps/worker`: Celery worker with source connector scaffolding and tasks for scraping, processing, reporting, and alerts.
- `apps/web`: Next.js App Router dashboard UI with login, onboarding, opportunities, sources, reports, alerts, settings, and admin views.
- `docker-compose.yml`: PostgreSQL with pgvector, Redis, MinIO, API, worker, and web.

## Local development

Copy `.env.example` to `.env` for local overrides, then run:

```bash
docker compose up --build
```

For lightweight local API development without Docker:

```bash
cd apps/api
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\python -m app.db.seed
.venv\Scripts\uvicorn app.main:app --reload
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

## Storage

By default, local development stores uploaded documents and generated report artifacts under `STORAGE_DIR`.
Docker Compose sets `STORAGE_BACKEND=s3` and points the API/worker to the bundled MinIO service.
For production, keep the same S3-compatible variables and replace the endpoint/credentials with the target provider.

## Deployment

See [DEPLOYMENT.md](./DEPLOYMENT.md) for the recommended free-stack deployment plan.
The short version is:

- frontend on Vercel;
- database on Neon with `pgvector`;
- Redis on Upstash;
- files on Cloudflare R2;
- API and worker on Render.

The repository also includes:

- `.github/workflows/ci.yml` for GitHub Actions checks on push and pull request;
- `render.yaml` as a Render blueprint for the API and worker services.

## Versioning

See [VERSIONING.md](./VERSIONING.md) for the GitHub release flow and semantic versioning rules.

## Scheduled Work

Docker Compose includes a Celery worker and `worker-beat`. Beat triggers internal API jobs with `INTERNAL_API_KEY`:

- enabled source checks every 30 minutes;
- due scheduled email alerts every 5 minutes.

Scraping can run in two modes:

- `SCRAPING_EXECUTION_MODE=inline` runs manual source captures inside the API request. This is the safest option for
  free deployments where a background worker might sleep or be unavailable.
- `SCRAPING_EXECUTION_MODE=worker` queues source runs in Celery and completes them through the protected internal callback
  `/api/v1/internal/source-runs/{run_id}/complete`. Use it only when the worker service is confirmed healthy.

`SCRAPING_EXECUTION_MODE=auto` keeps the legacy behavior: it queues only when `USE_WORKER=true`; otherwise it falls back
to inline execution.

## Source Connectors

The worker includes connector implementations for:

- `grants-gov`: Grants.gov public `search2` API connector using `https://api.grants.gov/v1/api/search2`;
- `grants-gov-rss`: Grants.gov public RSS feed connector using `https://www.grants.gov/rss/GG_OppModByCategory.xml`;
- `novo-nordisk-grants`: Novo Nordisk Foundation WordPress grants API with pagination (`wp-json/wp/v2/grant`);
- `horizon-europe-sedia`: Horizon Europe SEDIA search API for EU funding calls;
- `minciencias`: Minciencias Colombia convocatoria listing connector using `https://minciencias.gov.co/convocatorias/todas`;
- `innpulsa`: iNNpulsa Colombia convocatoria listing connector using `https://www.innpulsacolombia.com/convocatorias.html`;
- `apc-colombia`: APC Colombia convocatorias listing connector using `https://www.apccolombia.gov.co/modalidades-de-cooperacion/convocatorias`;
- `eu-funding-tenders`: European Commission calls-for-proposals listing using the EU Funding & Tenders Portal;
- `wellcome-grants`, `gates-foundation-grants`, `dfg-grants`, `colfuturo-convocatorias`, `mincit-innovacion`: HTML listing sources via the generic HTML connector;
- generic WordPress grants: reusable connector for any `wp-json/wp/v2/*` grants endpoint;
- generic RSS: fallback parser for absolute-link RSS feeds;
- generic HTML: fallback parser for simple public source pages.

Wave 1 expands the default seed from 19 to 26 sources. Use `POST /api/v1/admin/sources/reseed-defaults` in production to insert new defaults without re-registering the organization.

## Technology Watch Process

Use this monthly checklist to evaluate new funding sources:

1. Discover portals (`/grant`, `/funding`, `/convocatorias`), RSS feeds, and public APIs (`/wp-json/`, OpenAPI docs).
2. Score each candidate (1-5) on technical access, URL stability, structured format, coverage, relevance, legal/ToS, and latency.
3. Classify the connector: RSS seed-only, generic API/HTML, reusable WordPress grants, or dedicated connector.
4. Validate with `POST /api/v1/internal/connectors/probe` before enabling in production.
5. Add to `seed.py`, run reseed, execute a manual source run, and monitor Admin health for 3+ runs.

Discard sources that require login, CAPTCHA, block cloud IPs, or expose only scanned PDFs.

Connector tests use local fixtures and do not require internet access.
