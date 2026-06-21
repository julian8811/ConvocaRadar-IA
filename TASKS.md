# ConvocaRadar IA Task Map

## Done in this MVP scaffold

- Monorepo structure and Docker Compose.
- FastAPI API with SQLAlchemy models, Pydantic schemas, auth, CRUD services, report export, scoring, heuristic extraction, and seed data.
- Celery worker skeleton with connector interface, generic HTML connector, and report/alert tasks.
- Next.js frontend with a complete institutional dashboard shell and MVP screens.
- Initial backend tests for auth, source runs, opportunity listing, scoring, reports, and SSRF guardrails.
- Alembic migration scaffold with an initial schema migration.
- Protected internal scheduler endpoints plus Celery Beat jobs for enabled sources and due alerts.
- Async manual source runs with Celery completion callbacks for `source_runs`, `tasks`, and normalized opportunities.
- First real source connector: Grants.gov public `search2` API, with fixture-based worker tests.
- Generic RSS connector plus Grants.gov RSS source seed, with fixture-based worker tests.
- Minciencias Colombia connector and source seed, with fixture-based worker tests.
- iNNpulsa Colombia connector and source seed, with fixture-based worker tests.

## Next implementation slices

- Add real provider adapter for AI extraction and scoring.
- Add source-specific connector for Funding & Tenders.
- Add Playwright E2E tests across web/API.
- Add Sentry/OpenTelemetry and production deployment manifests.
