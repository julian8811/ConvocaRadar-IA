# ConvocaRadar IA Task Map

## Completed in this MVP

- Monorepo structure and Docker Compose.
- FastAPI API with SQLAlchemy models, Pydantic schemas, auth, CRUD services, report export, scoring, heuristic extraction, and seed data.
- Celery worker with connector interface, dedicated connectors for 38 sources, and report/alert tasks.
- Next.js frontend with institutional dashboard, registration, semantic search, admin guard, and MVP screens.
- Backend tests for auth, source runs, opportunity listing, scoring, reports, SSRF guardrails, and semantic search.
- Alembic migration scaffold with an initial schema migration.
- Protected internal scheduler endpoints plus Celery Beat jobs for enabled sources and due alerts.
- Async manual source runs with Celery completion callbacks for `source_runs`, `tasks`, and normalized opportunities.
- OpenAI-ready extraction and embeddings when `LLM_PROVIDER=openai` and API keys are configured.
- Automatic bootstrap scrape of priority sources when the database has no opportunities.
- Optional Sentry integration via `SENTRY_DSN`.
- Playwright E2E smoke test for login and dashboard navigation.

## Remaining for production operations

- Provision external services (Vercel, Neon, Upstash, R2, Render) and wire environment variables.
- Configure real SMTP credentials for alert delivery.
- Run connector probe checks against live sources after each deploy.
- Expand Playwright coverage across reports, alerts, and source runs in CI with a live API service.
