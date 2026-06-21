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

When `USE_WORKER=true`, manual source runs are queued in Celery and completed through the protected internal callback
`/api/v1/internal/source-runs/{run_id}/complete`. When `USE_WORKER=false`, the API keeps the local development fallback.

## Source Connectors

The worker includes connector implementations for:

- `grants-gov`: Grants.gov public `search2` API connector using `https://api.grants.gov/v1/api/search2`;
- `grants-gov-rss`: Grants.gov public RSS feed connector using `https://www.grants.gov/rss/GG_OppModByCategory.xml`;
- `minciencias`: Minciencias Colombia convocatoria listing connector using `https://minciencias.gov.co/convocatorias/todas`;
- `innpulsa`: iNNpulsa Colombia convocatoria listing connector using `https://www.innpulsacolombia.com/convocatorias.html`;
- `apc-colombia`: APC Colombia convocatorias listing connector using `https://www.apccolombia.gov.co/modalidades-de-cooperacion/convocatorias`;
- `eu-funding-tenders`: European Commission calls-for-proposals listing using the EU Funding & Tenders Portal;
- generic RSS: fallback parser for absolute-link RSS feeds;
- generic HTML: fallback parser for simple public source pages.

Connector tests use local fixtures and do not require internet access.
