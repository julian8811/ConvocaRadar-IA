# Scraper Pipeline — 021 Optimization

## Overview
Pipeline was starving: sequential `_run_periodic_source_sweep` took 45-60m for 75 due sources (>30m interval), only 30/91 ran daily. ~20m/day sync HEAD blocking + 25s/source serial embeddings wasted.

## Architecture after 021

### Parallel Sweep (REQ-SP-01)
`apps/api/app/main.py:_run_periodic_source_sweep` uses `asyncio.Semaphore(6)` capped by `SCRAPING_MAX_CONCURRENCY` (default 6, `max(1, min(6, config))`). Each source gets its own DB session. Wall-time target <15m for 75 sources. `SCRAPING_MAX_CONCURRENCY=1` restores sequential for rollback.

### Priority Queue (REQ-PQ-01)
`scraper/priority_queue.py:PriorityQueue` orders by tier `strategic(0) > complementary(1) > experimental(2) > untiered(3)`, staleness second. Dedup by id, defers domain-throttled to next cycle. `build_priority_queue(due_sources).drain_ordered()` wired into sweep so strategic always first. Overhead <500ms for 89 sources.

### Bulk Dedup (REQ-OI-02)
`services/opportunity.py:preload_external_ids` + `clear_bulk_cache` — 1 query/source instead of N. Wired in `scraper/runner.py:_persist_opportunities`: preload per-source external_id sets before loop, clear after batch. Falling back to 20-chunk retry on rate-limit.

### Domain Budget & Playwright Isolation (REQ-CF-02, REQ-CF-01)
`scraper/domain_budget.py:DomainBudgetManager` — per-domain token bucket (max_concurrent + delay_seconds), thread-safe, fnmatch globs. Singleton `get_domain_budget()`. Playwright isolated via `scraper/playwright_pool.py:PlaywrightBrowserPool` (slot acquire/release, crash in A does not affect B). Connectors delegate budget check; shared `httpx.AsyncClient` from `core/http_client.py` reused (no per-request sync clients).

### Batch AI (REQ-OI-02)
`services/embeddings.py:EmbeddingBatchService` + `build_embeddings_batch` chunk 32 (retry chunk 20). `core/ai.py:extract_opportunities_structured_batch` chunk 20 concurrent gather. p95 <5s per source (was 25s). Local-first fallback when `LLM_PROVIDER=local`.

### Source Health (REQ-SH-01/02)
Auto-pause after 5 consecutive empty/timeout (`scoring.should_auto_pause`, `runner.selector_failures >=5` and `consecutive_empty_runs`). Resets on partial success. Experimental daily→weekly migration `0013` respects allowlist (`grants-gov`, etc.) and `connector_config.manual_frequency` override. Stale >30d flagged via health job.

### Observability (REQ-OBS-01)
`scraper/metrics.py` — in-process histogram (scrape_duration p50/p95/avg), counters (items_found, scrapes, errors), gauges (health_score). Emitted via `structlog` per source (`scrape_metrics`, `scraper_source_complete` with latency_ms) and exposed at `/metrics` alongside DB counts. Sentry spans fetch→parse→score via `SentryTracing` if configured.

### Indices (0014)
`ix_sources_enabled_tier_last_run`, `ix_sources_enabled_last_run`, `ix_source_runs_source_id_created_at`, `ix_opportunities_source_id` — sweep/scoring p95 <100ms.

## Migrations 0012-0014
Linear chain: `0012_fix_sena_allowed_domains` → `0013_reclassify_experimental_frequency` → `0014_scraper_pipeline_indices`. Reversible, indices drop on downgrade. Tested via `tests/test_migrations_chain.py`.

## Rollback
Set `SCRAPING_MAX_CONCURRENCY=1` (sequential), re-enable sync HEAD stub via flag. Indices reversible. Opportunities append-only.

## Config
`SCRAPING_MAX_CONCURRENCY=6`, `scraping_max_source_seconds=180`, `per_connector_timeout_seconds=180`, `LLM_PROVIDER=local|cloudflare|openai`.
