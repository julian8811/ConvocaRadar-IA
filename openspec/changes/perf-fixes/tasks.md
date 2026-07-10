# Tasks: Change 1 — Core Performance Fixes

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~460 (+510 / -50) |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 (HTTP Pool) → PR 2 (Async Embeddings) → PR 3 (N+1 Removal) |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | HTTP client pool + replace inline clients | PR 1 | Base: main. No breaking change, safe. |
| 2 | `build_embedding` async + sync bridge + propagate | PR 2 | Base: main. Depends on PR 1's pool only conceptually (no code dep if merged). |
| 3 | Remove N+1 properties/fields + url-check endpoint | PR 3 | Base: main. Breaking change documented. |

---

## Phase 1: HTTP Client Pool — New `http_client.py` + Lifespan Wiring

- [ ] 1.1 **T-1** Test: write `test_http_client_lifecycle` — init returns clients, close cleans up, isolated from real network
- [ ] 1.2 **T-2** Create `apps/api/app/core/http_client.py` — `http_client()` (async), `sync_http_client()` (sync), `close_clients()`, configurable limits/timeout
- [ ] 1.3 **T-3** Wire into `apps/api/app/main.py` lifespan — init async client on `app.state`, close on shutdown
- [ ] 1.4 **T-4** Test: write `test_http_client_replaces_inline` — verify `_call_llm`, `_call_openai_embedding`, connectors use the global client (mock patching)
- [ ] 1.5 **T-5** Replace `httpx.AsyncClient()` in `apps/api/app/core/ai.py` (`_call_llm:333`, `_call_openai_embedding:467`) → `http_client()` with per-call `timeout=`
- [ ] 1.6 **T-6** Replace `httpx.Client()` in `apps/api/app/services.py` (`url_is_reachable:1002`) → `sync_http_client()`
- [ ] 1.7 **T-7** Replace `httpx.AsyncClient()` in `apps/api/app/connectors/common.py` (lines 385, 432) → `http_client()`
- [ ] 1.8 **T-8** Replace `httpx.AsyncClient()` in `apps/api/app/connectors/wordpress_grants.py` (line 93) → `http_client()`

## Phase 2: Embedding Async Migration — `build_embedding` → `async def` + Sync Bridge

- [ ] 2.1 **T-9** Test: write `test_build_embedding_async` — mock `_call_openai_embedding`, verify `await` works; test local hash fallback; test `build_embedding_sync` bridge
- [ ] 2.2 **T-10** Convert `build_embedding()` in `apps/api/app/core/ai.py` to `async def`, remove `new_event_loop()/run_until_complete()/loop.close()`, extract local hash to sync helper
- [ ] 2.3 **T-11** Add `build_embedding_sync()` bridge in `apps/api/app/core/ai.py` — wraps with `asyncio.run()`

## Phase 3: Propagate Async — Services, Routes, CLI Scripts

- [ ] 3.1 **T-12** Test: write `test_upsert_embedding_async` and `test_rebuild_embeddings_async` — mock `build_embedding`, verify DB write + model_version
- [ ] 3.2 **T-13** Convert `upsert_opportunity_embedding()` in `apps/api/app/services.py` to `async def` — `await build_embedding()`
- [ ] 3.3 **T-14** Convert `rebuild_opportunity_embeddings()` in `apps/api/app/services.py` to `async def` — `await build_embedding()`
- [ ] 3.4 **T-15** Update `semantic_search_opportunities()` in `apps/api/app/services.py:753` → `await build_embedding()`
- [ ] 3.5 **T-16** Update `reanalyze_opportunity()` in `apps/api/app/services.py:731` → `await upsert_opportunity_embedding()`
- [ ] 3.6 **T-17** Convert handlers in `apps/api/app/api/v1/opportunities.py` that call async deps: `update_opportunity`, `reanalyze_single_opportunity`, `reanalyze_all_opportunities` → `async def`
- [ ] 3.7 **T-18** Convert `rebuild_embeddings_admin` in `apps/api/app/api/v1/admin.py` → `async def`
- [ ] 3.8 **T-19** Update `apps/api/app/db/seed_admin.py` — use `build_embedding_sync()` bridge
- [ ] 3.9 **T-20** Update `apps/api/app/db/backfill_close_dates.py` — use `build_embedding_sync()` bridge
- [ ] 3.10 **T-21** Write integration test: hit a reanalyze endpoint, verify no `RuntimeError` / event-loop crash

## Phase 4: Remove N+1 — Model Properties + Schema Fields + url-check Endpoint

- [ ] 4.1 **T-22** Test: write `test_url_check_endpoint` — mock `url_is_reachable` for both URLs, verify response shape; test `opportunity` with `None` URLs
- [ ] 4.2 **T-23** Remove `official_url_is_reachable` and `application_url_is_reachable` properties from `Opportunity` in `apps/api/app/models.py:247-261`
- [ ] 4.3 **T-24** Remove `official_url_is_reachable` and `application_url_is_reachable` fields from `OpportunityRead` in `apps/api/app/schemas.py:289-290`
- [ ] 4.4 **T-25** Add `GET /opportunities/{id}/url-check` endpoint in `apps/api/app/api/v1/opportunities.py` — returns `{"official_url": bool, "application_url": bool}` using `url_is_reachable_async`

## Phase 5: Cleanup + Documentation

- [ ] 5.1 **T-26** Write regression test: list 100 opportunities (`GET /opportunities`) completes in <500ms (no N+1 HTTP)
- [ ] 5.2 **T-27** Update `CHANGELOG.md` — document breaking schema change (OpportunityRead loses `url_is_reachable` fields), mark as v0.2.0
- [ ] 5.3 **T-28** Run full test suite, fix any regressions from sync→async endpoint changes

---

## Dependency Graph

```
T-1 ──▶ T-2 ──▶ T-3
  │               │
  └──▶ T-4 ──▶ T-5 ──▶ T-6 ──▶ T-7 ──▶ T-8
                                        │
                  T-9 ──▶ T-10 ──▶ T-11
                   │                   │
                   └──▶ T-12 ──▶ T-13 ──▶ T-14 ──▶ T-15
                                     │          │
                                     ├──▶ T-16 ──┤
                                     │          │
                                     │          ▼
                                     │       T-17 ──▶ T-18
                                     │          │
                                     │          └──▶ T-19 ──▶ T-20 ──▶ T-21
                                     │
                  T-22 ──▶ T-23 ──▶ T-24 ──▶ T-25
                   │
                   └──▶ T-26 ──▶ T-27 ──▶ T-28

PR 1: T-1 to T-8
PR 2: T-9 to T-21  (requires PR 1)
PR 3: T-22 to T-28 (requires PR 1, independent of PR 2)
```

## Key Risks per Task

| Task | Risk |
|------|------|
| T-5 | `_call_llm` timeouts — per-call `timeout=` override must not use global client default |
| T-7, T-8 | Connectors use Playwright + httpx — only replace the httpx pieces, not Playwright contexts |
| T-10 | Local hash path is pure sync — keep it synchronous, no `await` needed |
| T-17 | Converting sync FastAPI handlers → async can surface hidden blocking calls in DB queries |
| T-19, T-20 | CLI scripts run outside FastAPI — `asyncio.run()` needs no running event loop |
| T-25 | `url_is_reachable_async` must still call `lru_cache` — cache key includes URL only, not client |
