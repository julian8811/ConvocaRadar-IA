# ConvocaRadar-IA

Intelligent grants and opportunities monitoring platform. Scrapes, deduplicates, scores, and alerts on funding opportunities from ~50 source connectors across Latin America, the United States, Europe, and global organizations.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Frontend (Next.js 15, React 19, TanStack Query)        │
│  apps/web/        → port 3002 (host) → 3000 (container) │
├─────────────────────────────────────────────────────────┤
│  Backend (FastAPI, SQLAlchemy 2.0, structlog)            │
│  apps/api/        → port 8000                            │
│    ├── connectors/  ~50 source connector modules          │
│    ├── scraper/     Runner, dispatcher, recovery, DOM    │
│    ├── services/    Scoring, dedup, export, enrichment   │
│    ├── core/        Config, security, email, AI, HTTP    │
│    ├── db/          Models, migrations, seed             │
│    └── api/v1/      12 routers, 85 REST endpoints        │
├─────────────────────────────────────────────────────────┤
│  Worker (inline scheduler, no Celery/Redis)              │
│  Runs every 30 min via asyncio loop in worker process    │
├─────────────────────────────────────────────────────────┤
│  PostgreSQL 16 + pgvector                                │
│  MinIO (S3-compatible object storage)                    │
└─────────────────────────────────────────────────────────┘
```

The scheduler runs inline using an `asyncio` loop — no Celery, no Redis, no external task queue. A dedicated `worker` container runs the scheduler loop; the `api` container serves requests. Both share the same codebase.

## Quick Start

```sh
# 1. Clone and configure
git clone https://github.com/julian8811/ConvocaRadar-IA.git
cd ConvocaRadar-IA
cp .env.example .env
# Edit .env — set INTERNAL_API_KEY, JWT_SECRET y RESET_TOKEN_SECRET (min 32 chars c/u)

# 2. Start infrastructure
docker compose up -d postgres minio

# 3. Build and start the API
docker compose build api && docker compose up -d api

# 4. (Optional) start the frontend
docker compose build web && docker compose up -d web

# 5. Verify
curl http://localhost:8000/health

# 6. API docs
open http://localhost:8000/docs
```

### Bootstrap an admin user

```sh
docker compose exec api convocaradar-seed-admin \
  --email admin@example.com \
  --password-env INTERNAL_API_KEY
```

## Stack

### Backend (`apps/api/`)

| Component | Technology |
|-----------|-----------|
| Runtime | Python 3.12 |
| Framework | FastAPI (>=0.115) |
| ORM | SQLAlchemy 2.0 (>=2.0.32) |
| Migrations | Alembic (>=1.13) |
| Database driver | psycopg 3 (binary) |
| Scraping | Playwright (+ Chromium), selectolax, httpx |
| PDF parsing | pypdf |
| Auth | python-jose (JWT) with password rotation tracking |
| Logging | structlog |
| Vector search | pgvector |
| Object storage | boto3 (S3-compatible, MinIO) |
| Reports | Jinja2, openpyxl, reportlab |
| Validation | pydantic v2, email-validator |
| Error tracking | Sentry SDK |

### Frontend (`apps/web/`)

| Component | Technology |
|-----------|-----------|
| Framework | Next.js 15 (Turbopack dev) |
| UI | React 19, Tailwind CSS v4 |
| State / data | TanStack React Query v5 |
| Charts | Recharts |
| Icons | Lucide React |
| Toasts | Sonner |
| Testing | Vitest, Playwright, Testing Library |

### Database

- PostgreSQL 16 with pgvector extension
- pgvector for AI-powered embedding similarity search
- Full-text search via PostgreSQL FTS
- Alembic for versioned schema migrations (10 migration files)

### AI / Embeddings

- **Default**: Cloudflare Workers AI (embedding + chat inference)
- **Fallback**: Local hash-based embedding (no external dependency)
- Embedding dimension: 1024
- Used for: opportunity scoring, deduplication, semantic search, enrichment

### Email

- **Resend API** (free tier: 100 emails/day)
- Digest: weekly email summaries for each organization
- Alerts: event-driven notifications for high-priority opportunities

### Authentication

- JWT-based (HS256, python-jose)
- Access token expiry: configurable (default 60 min)
- Password rotation tracking (enforced per org policy)
- CSRF protection via `X-CSRF-Protection` custom header
- Internal API key for machine-to-machine communication
- Rate limiting: configurable per-IP window (default 120 req/min)

## Project Structure

```
apps/
├── api/                              # FastAPI backend
│   ├── app/
│   │   ├── connectors/               # ~50 source connector modules
│   │   │   ├── base.py               # SourceConnector protocol + dataclasses
│   │   │   ├── registry.py           # @register decorator + get_connector()
│   │   │   ├── factory.py            # connector_for() dispatcher
│   │   │   ├── generic_html.py       # Generic HTML scraper
│   │   │   ├── configurable_html.py  # Declarative config-based scraper
│   │   │   ├── rss.py                # RSS/XML feed scraper
│   │   │   ├── pdf.py                # PDF-based scraper
│   │   │   ├── api.py                # REST API-based scraper
│   │   │   ├── hybrid.py             # Multi-stage scraper
│   │   │   ├── manual.py             # Manually entered sources
│   │   │   ├── grants_gov.py         # Grants.gov (US)
│   │   │   ├── nsf.py                # NSF funding (US)
│   │   │   ├── minciencias.py        # MinCiencias (Colombia)
│   │   │   ├── innpulsa.py           # Innpulsa (Colombia)
│   │   │   ├── bdn_convocatorias.py   # BDN (Spain)
│   │   │   └── ...                   # 35+ additional connectors
│   │   │
│   │   ├── scraper/                  # Scraping pipeline
│   │   │   ├── runner.py             # Orchestrates fetch→parse→persist
│   │   │   ├── dispatcher.py         # Guards against duplicate runs
│   │   │   ├── recovery.py           # Stale run recovery on startup
│   │   │   ├── dom_monitor.py        # DOM change detection
│   │   │   ├── domain_budget.py      # Domain rate limiting
│   │   │   ├── errors.py             # Error classification
│   │   │   └── probe.py              # Source contract validation
│   │   │
│   │   ├── services/                 # Business logic
│   │   │   ├── scoring.py            # ML-based opportunity scoring
│   │   │   ├── dedup.py              # Deduplication engine
│   │   │   ├── embeddings.py         # Vector embedding generation
│   │   │   ├── search.py             # Full-text + vector search
│   │   │   ├── export.py             # XLSX/PDF report generation
│   │   │   ├── validation.py         # Source URL validation
│   │   │   └── _legacy.py            # Noise detection, enrichment
│   │   │
│   │   ├── core/                     # Shared infrastructure
│   │   │   ├── config.py             # Pydantic Settings (53 env vars)
│   │   │   ├── security.py           # Password hashing, password rotation
│   │   │   ├── http_client.py        # Shared httpx client pool
│   │   │   ├── email.py              # SMTP + Resend email dispatch
│   │   │   ├── ai.py                 # Cloudflare Workers AI integration
│   │   │   ├── storage.py           # Local / S3 file storage
│   │   │   ├── logging.py            # structlog configuration
│   │   │   ├── rate_limit.py         # Token bucket rate limiter
│   │   │   ├── task_queue.py         # In-memory task queue
│   │   │   └── time.py               # Timezone helpers
│   │   │
│   │   ├── db/                       # Database layer
│   │   │   ├── session.py            # SQLAlchemy engine + session factory
│   │   │   ├── seed.py               # 93 source definitions (idempotent)
│   │   │   ├── seed_admin.py         # CLI to bootstrap admin users
│   │   │   ├── bootstrap.py          # Startup data initialization
│   │   │   ├── migrate.py            # Idempotent migration runner
│   │   │   └── ...                   # Migration scripts, repair tools
│   │   │
│   │   ├── api/v1/                   # REST API layer
│   │   │   ├── router.py             # Route aggregation + CSRF deps
│   │   │   ├── auth.py               # Login, register, token refresh
│   │   │   ├── dashboard.py          # Aggregate metrics
│   │   │   ├── sources.py            # Source CRUD + sweep trigger
│   │   │   ├── opportunities.py      # Opportunity listing, details, search
│   │   │   ├── organizations.py      # Organization management
│   │   │   ├── alerts.py             # Alert configuration + dispatch
│   │   │   ├── reports.py            # XLSX/PDF report download
│   │   │   ├── admin.py              # Admin panel endpoints
│   │   │   ├── ai.py                 # AI chat + enrichment
│   │   │   ├── tasks.py              # Task status tracking
│   │   │   ├── ops.py                # Ops health + metrics
│   │   │   └── internal.py           # Internal API key endpoints
│   │   │
│   │   ├── models.py                 # SQLAlchemy ORM models
│   │   ├── schemas.py                # Pydantic request/response schemas
│   │   ├── main.py                   # FastAPI app factory, lifespan, middleware
│   │   └── worker.py                 # Dedicated scheduler process
│   │
│   └── tests/                        # 942+ tests (65+ test files)
│       ├── test_auth.py
│       ├── test_scoring.py
│       ├── test_connectors.py
│       ├── test_dedup.py
│       └── ...
│
├── web/                              # Next.js frontend
│   ├── app/
│   │   ├── (app)/                    # Authenticated pages
│   │   │   ├── dashboard/            # Metrics dashboard
│   │   │   ├── opportunities/        # Opportunity list + detail
│   │   │   ├── sources/              # Source management + run history
│   │   │   ├── alerts/               # Alert rules configuration
│   │   │   ├── reports/              # Report generation + download
│   │   │   ├── settings/             # Organization settings
│   │   │   ├── admin/                # Admin panel
│   │   │   └── onboarding/           # First-run setup flow
│   │   ├── login/                    # Login page
│   │   ├── register/                 # Registration page
│   │   └── page.tsx                  # Landing / redirect
│   │
│   └── components/
│       ├── ui/                       # 7 primitive components (button, card, etc.)
│       ├── dashboard/                # Dashboard widgets + charts
│       │   └── charts/               # 6 chart components (Recharts)
│       ├── app-shell.tsx             # Layout shell with nav
│       ├── query-provider.tsx        # TanStack Query provider
│       └── theme-toggle.tsx          # Light/dark toggle

scripts/              # Maintenance and deployment scripts
  └── sync-next-output.mjs
```

## Configuration

Key environment variables (see `.env.example` for defaults):

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `sqlite:///./convocaradar.db` |
| `JWT_SECRET` | JWT signing key (min 32 chars) | — |
| `INTERNAL_API_KEY` | Internal API key (min 32 chars) | — |
| `RESEND_API_KEY` | Resend API key for email | — |
| `LLM_PROVIDER` | AI provider: `cloudflare` or `local` | `local` |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account ID | — |
| `CLOUDFLARE_API_TOKEN` | Cloudflare API token | — |
| `S3_ENDPOINT_URL` | S3-compatible storage endpoint | — |
| `SENTRY_DSN` | Sentry error tracking DSN | — |
| `SCHEDULER_ENABLED` | Enable background source sweep | `true` |
| `SCHEDULER_INTERVAL_SECONDS` | Sweep interval | `1800` |
| `SCRAPING_MAX_CONCURRENCY` | Max concurrent scrapes | `6` |
| `SCRAPING_PROXY_LIST` | Proxy rotation URLs | — |
| `FRONTEND_URL` | Frontend URL for CORS + links | `http://localhost:3002` |
| `WEB_PORT` | Host port for web container (avoid 3000 collision) | `3002` |
| `APP_TIMEZONE` | Application timezone | `America/Bogota` |

## Testing

```sh
# Backend tests (942+ tests, 65+ files)
cd apps/api
pip install -e ".[dev]"
pytest tests/                  # all tests
pytest tests/ -k "test_auth"   # auth-specific tests
pytest tests/ --coverage       # with coverage report

# Frontend tests
cd apps/web
npm run test                   # Vitest unit tests
npm run test:e2e              # Playwright E2E tests

# Full suite via Make
make test
```

### Linting

```sh
make lint                        # Ruff + ESLint
cd apps/api && ruff check app    # Backend only
cd apps/web && npm run lint      # Frontend only
```

## Connector Architecture

All source connectors implement the `SourceConnector` protocol defined in `apps/api/app/connectors/base.py`:

```python
class SourceConnector(Protocol):
    source_key: str

    async def fetch(self) -> RawSourceResult: ...
    async def parse(self, raw: RawSourceResult) -> list[OpportunityCandidate]: ...
    async def validate(self, candidate: OpportunityCandidate) -> ValidationResult: ...
```

### Registration pattern

Connectors are registered via the `@register` decorator (36 registered connectors) and retrieved through a factory dispatcher:

```python
from app.connectors.registry import register, get_connector

@register("grants-gov")
class GrantsGovConnector:
    ...

# Later:
conn = get_connector("grants-gov", "https://api.example.com")
```

### Factory dispatcher

`connector_for()` in `factory.py` handles three tiers:

1. **Special cases** — connectors with non-standard `__init__` (Finep, DANE, DevelopmentAid, etc.)
2. **Registered connectors** — standard `cls(base_url)` via `get_connector()`
3. **Fallback** — generic HTML, RSS, PDF, Hybrid, API, or Manual connectors based on `source_type`

### Connector types

| Type | Class | Description |
|------|-------|-------------|
| Dedicated | Various | Custom parser per source (Grants.gov, NSF, MinCiencias, etc.) |
| Generic HTML | `GenericHtmlConnector` | CSS-selector-based scraping from seed config |
| Configurable HTML | `ConfigurableHtmlConnector` | Declarative YAML/dict-based scraping config |
| RSS | `RssConnector` | Standard RSS/XML feed parsing |
| PDF | `PdfConnector` | PDF document scraping |
| API | `ApiConnector` | REST API integration |
| Hybrid | `HybridConnector` | Multi-stage (e.g., sitemap + detail page) |
| Manual | `ManualConnector` | Manually entered opportunities |

### Source ecosystem

- **93 source keys** defined in `seed.py` across LatAm, US, Europe, and global orgs
- **~50 connector modules** in `connectors/`
- **36 registered connectors** via `@register`
- Sources are tiered and auto-paused when consecutive empty runs exceed a threshold

## Scraping Pipeline

Each source scrape follows a deterministic lifecycle:

```
┌─────────┐   ┌─────────┐   ┌──────────┐   ┌────────┐   ┌────────┐   ┌─────────┐   ┌─────────┐
│  FETCH  │ → │  PARSE  │ → │  ENRICH  │ → │ DEDUP  │ → │ SCORE  │ → │  EMBED  │ → │  ALERT  │
│         │   │         │   │  (AI+)   │   │        │   │        │   │         │   │         │
│ HTTP /  │   │ HTML /  │   │ Cloudf.  │   │ URL +  │   │ ML     │   │ pgvec. │   │ Email   │
│ Playw.  │   │ select. │   │ regex    │   │ hash   │   │ rank   │   │ store  │   │ digest  │
└─────────┘   └─────────┘   └──────────┘   └────────┘   └────────┘   └─────────┘   └─────────┘
```

### Pipeline phases

1. **Fetch** — HTTP GET via httpx or Playwright (JS-rendered pages). Timeout, proxy rotation, user-agent customization.
2. **Parse** — Connector-specific parsing: selectolax CSS selectors, ElementTree XML, RSS feed parsing, PDF extraction.
3. **Enrich** — Cloudflare Workers AI enriches low-confidence candidates (title, summary, categories, close date). Regex fallback enrichment. Noise detection filters out 100% of non-opportunity pages.
4. **Dedup** — URL hash + external ID deduplication across runs. State persisted in `connector_config`.
5. **Score** — ML-based scoring per organization profile. Categories, entity affinity, closing-soon boost, language match.
6. **Embed** — 1024-dim vector embeddings stored in pgvector. Powers semantic search.
7. **Alert** — Event-driven and digest-based email alerts via Resend API.

## API Documentation

When the API is running, interactive OpenAPI documentation is available at:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### API versioning

All endpoints are prefixed with `/api/v1/`. Internal endpoints use `/api/v1/internal/` with API key authentication. Public endpoints use JWT cookies + CSRF protection.

### Router modules (12 total)

| Module | Prefix | Tags |
|--------|--------|------|
| `auth` | `/api/v1/auth` | Auth |
| `dashboard` | `/api/v1/dashboard` | Dashboard |
| `organizations` | `/api/v1/organizations` | Organizations |
| `sources` | `/api/v1/sources` | Sources |
| `opportunities` | `/api/v1/opportunities` | Opportunities |
| `reports` | `/api/v1/reports` | Reports |
| `alerts` | `/api/v1/alerts` | Alerts |
| `ai` | `/api/v1/ai` | AI |
| `admin` | `/api/v1/admin` | Admin |
| `ops` | `/api/v1/ops` | Ops |
| `tasks` | `/api/v1/tasks` | Tasks |
| `internal` | `/api/v1/internal` | (API key auth) |

## Contributing

1. Open an issue to discuss the change before opening a PR.
2. Follow the existing code style — Ruff linting with line-length 100.
3. Backend: Python 3.12+ with type annotations on all public interfaces.
4. Frontend: TypeScript strict mode, Tailwind v4 utility classes.
5. All new connectors must implement the `SourceConnector` protocol.
6. All new functionality must include tests. Existing tests must pass.
7. Run `make lint` and `make test` before committing.
8. Never commit `.env` files or secrets. Use `.env.example` for documentation.

```sh
# Install dev dependencies
cd apps/api && pip install -e ".[dev]"

# Run linter
ruff check app

# Run tests
pytest tests/

# Keep migrations as the single source of truth for schema changes
make backup     # before destructive operations
make migrate    # apply pending migrations
```

## License

MIT
