## Exploration: Scraper System Rehabilitation

### Current State

#### The Two Competing Code Paths

**Path A — Sync (`execute_source_run_locally`)**:
```
POST /sources/run-all          (sources.py:334, ThreadPoolExecutor)
  → execute_source_run_locally (_legacy.py:1329, sync wrapper)
    → asyncio.new_event_loop()
      → run_source_inline       (runner.py:147, async)
        → _scrape_candidates_with_timeout → _scrape_candidates
```

**Path B — Async (`run_source_inline` / `run_source`)**:
```
Periodic sweep                  (main.py:52, asyncio loop)
  → run_source                  (dispatcher.py:31)
    → run_source_inline         (runner.py:147, async)

POST /sources/{id}/run           (sources.py:313, FastAPI sync)
  → execute_source_run_locally   (same sync wrapper)
```

**When `run-all` is called vs periodic sweep**:
- `run-all` (line 334): Creates a **daemon thread**, then a `ThreadPoolExecutor` with max_workers=2. Each source's scrape runs in its own thread, each thread creates its own event loop via `asyncio.new_event_loop()`. **Every source gets a fresh independent event loop in its own thread** — this is extremely wasteful.
- **Periodic sweep** (main.py:52): Runs in the main asyncio loop. Iterates sources sequentially via `await run_source(db, source)`. One loop, sequential, non-parallel. Checks `source_due_for_scraping` and `auto_paused`.
- The periodic sweep calls `run_source` (dispatcher.py) which calls `run_source_inline` directly.
- `run-all` calls `execute_source_run_locally` which is a sync wrapper that ALSO calls `run_source_inline`.
- **They converge at the same function** (`run_source_inline`), but through different entry points. The `run-all` path also does extra work: source due checks happen in the request handler, not in the thread; the thread merely receives the pre-filtered `due_sources` list.

**Why two paths exist?**
- The legacy code (`_legacy.py`) was the original monolithic `services.py`. When the modular `scraper/` package was created, the async logic was extracted into `runner.py`.
- The old `execute_source_run_locally` was kept as a thin sync wrapper for endpoints that can't use async (FastAPI synchronous endpoints, `run-all`'s ThreadPoolExecutor).
- Adding `run_source` in `dispatcher.py` added a **third** entry point that checks for duplicate runs and Arq dispatch.
- **The periodic sweep uses `run_source` (dispatcher), while `run-all` bypasses the dispatcher entirely** — calling `execute_source_run_locally` directly. This means `run-all` does NOT check for existing running runs, does NOT check for auto_paused, and does NOT dispatch via Arq.

#### The Connector Construction Chaos

`factory.py` has **three overlapping construction mechanisms**:

1. **Registry pattern** (6 connectors): `@register("grants-gov")` → `get_connector(key, base_url)` constructs as `cls(base_url, **kwargs)`. Only 6 out of ~36 connector classes are registered: `grants-gov`, `grants-gov-rss`, `apc-colombia`, `innpulsa`, `minciencias`.

2. **If-elif chain** (~18 explicit branches): Hardcoded per-source-key instantiation from line 133-193. Each branch constructs the connector with different signatures — some take `(base_url)`, some take `(source_key, base_url)`, some call factory functions (`_heading_list_connector`, `_bdn_connector`).

3. **Fallback catch-all** (lines 193-220): Based on `source_type` (manual, pdf, hybrid, api, rss) or URL patterns (ends with `.xml`/`.rss`, contains `/wp-json/wp/v2/`). Falls through to `ConfigurableHtmlConnector` or `GenericHtmlConnector`.

The `connector_for` function receives **5 optional positional args** and **4 keyword args** — and different call sites pass different combinations:

```python
# From runner.py (the ASYNC path):
connector_for(source.key, source.base_url, source.source_type,
    entity_name=source.name, default_country=source.country,
    default_categories=source.category)

# From _legacy.py (legacy duplicate - identical code):
connector_for(source.key, source.base_url, source.source_type,
    entity_name=source.name, default_country=source.country,
    default_categories=source.category)

# From services.__init__ (re-export):
connector_for(source_key, base_url, source_type, ...)

# From internal.py (probe endpoint):
connector_for(payload.source_key, payload.base_url, payload.source_type)
# NOTE: This one does NOT pass entity_name/country/categories!
```

The fallback for grants-gov sources when no candidates are found creates a SECOND connector with `base_url=None` — this is a special-case hack.

#### The Test Problem

48 test files with mock HTML fixtures. Tests pass but:
- They test against static HTML that may not represent current real-world page structures
- All network calls are mocked (httpx, playwright)
- No tests actually hit real URLs
- The timeout errors seen in production (all 24 sources that ran) would never surface in tests
- No integration tests between the full pipeline

#### Error Taxonomy

All errors are handled the same way in `run_source_inline`:

```
except Exception as exc:
    run.status = "failed"
    run.error_message = str(exc)  # Single text field
    run.items_failed = 1
    source.last_error = str(exc)
    create_source_health_alert(...)
```

There is **no error classification**: timeouts (asyncio.TimeoutError), network errors (httpx.HTTPError), parse errors, auth errors — all become `run.status = "failed"` with `str(exc)`. The `items_failed` is always set to 1 regardless of how many items actually failed (it's not per-item).

The only exception is `asyncio.CancelledError` which has its own handler.

#### DOM Hash — Observational Only

`compute_dom_hash` is called during `_scrape_candidates` and stored in `source.dom_hash`. When the hash changes, a warning is logged. **It is never used to skip re-fetching or to trigger any automated action** — purely observational.

#### Caching

**Zero HTTP caching.** Every scrape makes a fresh HTTP request. No ETag, no If-Modified-Since, no local cache.

### Affected Areas

| File | Role |
|------|------|
| `apps/api/app/scraper/runner.py` | Core async scrape pipeline — fetch → parse → persist lifecycle |
| `apps/api/app/scraper/dispatcher.py` | Dispatch logic — checks duplicate runs, Arq vs inline |
| `apps/api/app/scraper/domain_budget.py` | Per-domain rate limiter (token bucket, thread-safe) |
| `apps/api/app/scraper/dom_monitor.py` | DOM hash computation and structural change detection |
| `apps/api/app/scraper/recovery.py` | Stale run cleanup (SQL update for runs >10min) |
| `apps/api/app/connectors/factory.py` | 220-line connector construction with 3 overlapping mechanisms |
| `apps/api/app/connectors/registry.py` | Decorator-based registration (6 connectors, built but underused) |
| `apps/api/app/connectors/common.py` | `fetch_httpx_text`, `render_page_html`, rate limiting, text helpers |
| `apps/api/app/connectors/generic_html.py` | Fallback HTML connector (626 lines) with URL resolution, JSON/JSON-LD, CSS selectors |
| `apps/api/app/connectors/configurable_html.py` | Declarative connector driven by JSON config (665 lines) |
| `apps/api/app/models.py` | Source (health fields: tier, auto_paused, dom_hash, etc.) and SourceRun |
| `apps/api/app/api/v1/sources.py` | `run-all` endpoint (ThreadPoolExecutor) and health endpoint |
| `apps/api/app/api/v1/internal.py` | Connector probe endpoint (exactly what we need for inventory) |
| `apps/api/app/main.py` | `_run_periodic_source_sweep` — 30-min async loop |
| `apps/api/app/services/_legacy.py` | The 2500-line legacy module — `execute_source_run_locally`, `connector_for` re-export, `create_source_health_alert` |
| `apps/api/app/services/__init__.py` | Facade re-exporting everything from `_legacy.py` |
| `apps/api/app/services/scoring.py` | Health score calculation (`calculate_source_health_score`) |

### Approaches

#### Approach 1: Probe-First Functional Inventory (Recommended)

**Description**: Build a one-shot probe tool that iterates all 126 sources, calls `connector_for` + `connector.fetch()` (with a short timeout per source), and classifies each as GREEN (fetched content), YELLOW (fetched but empty/error on parse), or RED (network timeout, DNS failure, or exception). Fix broken sources by either adding/repairing dedicated connectors or by pushing connector_config JSON into the Source model so ConfigurableHtmlConnector handles them. Only then unify the code paths.

- **Pros**: Lowest risk — doesn't touch the running system. Immediately reveals which 102 never-run sources actually work. The probe endpoint already exists at `/internal/connectors/probe`. Gives a data-driven triage list. Can be built as a standalone CLI script that uses the same internals.
- **Cons**: Doesn't fix timeouts. Doesn't address the dual code path problem. Takes manual effort per broken source.
- **Effort**: Medium (1-2 sprints for probe + initial triage; ongoing per-source fixes)

**Details**:
1. Build a `scripts/probe_all_sources.py` that:
   - Loads all sources from DB
   - For each: `connector_for(key, base_url, source_type)`, `connector.fetch()` with per-source timeout
   - Classifies: GREEN (200, content), YELLOW (200 but empty/no candidates), RED (exception/timeout)
   - Writes results to a CSV/DB table
2. For RED sources: diagnose root cause (broken URL, wrong connector type, site structure changed)
3. For YELLOW sources: try adding `connector_config` JSON to use ConfigurableHtmlConnector
4. For GREEN sources: mark as `tier=strategic` or `tier=complementary`
5. Meanwhile, fix the easy wins: `run-all` bypasses dispatcher (add dispatcher check), timeout values too low for some sources

#### Approach 2: Consolidate + Retire Legacy (Higher Risk)

**Description**: Delete the legacy path entirely. Rewrite `execute_source_run_locally` to use `run_source` (dispatcher). Make `run-all` use the dispatcher. Standardize on one entry point for all scrapes. Lift the registry pattern to cover ALL connectors (migrate the if-elif chain to `@register` decorators). Remove the dead code from `_legacy.py`.

- **Pros**: Clean architecture. Single code path. All runs get duplicate checks, auto_paused checks, Arq dispatch. Registry makes adding new connectors trivial.
- **Cons**: High risk of breaking production. Many connectors have non-standard `__init__` signatures that the registry can't handle. Renaming all connector `__init__` methods risks breaking tests. Doesn't address the fundamental problem (102 sources never tested).
- **Effort**: High (3-4 sprints). Must be done after the functional inventory.

#### Approach 3: Targeted Timeout Fix + Crawl Walk Run

**Description**: Don't touch the architecture. Just fix the timeout values, add per-connector timeouts, increase the default `scraping_max_source_seconds`, add retry logic with exponential backoff to `fetch_httpx_text`. Run the periodic sweep at higher frequency. Monitor failures. Fix each source as it breaks.

- **Pros**: Lowest effort. Quick wins. Addresses the most obvious failure mode (timeouts) without refactoring.
- **Cons**: Band-aid. Doesn't fix the 102 untested sources. Doesn't fix the architectural cruft. Timeout tuning is guesswork without the functional inventory. Connector construction chaos remains.
- **Effort**: Low (days)

### Recommendation

**Approach 1 (Probe-First Functional Inventory)**, with selective elements from Approach 3 as quick wins:

1. **Immediately**: Fix `run-all` to go through the dispatcher (line 438 calls `execute_source_run_locally` instead of `run_source` — this skips duplicate-run detection, auto-paused check, and Arq dispatch). This is a one-line fix.

2. **Immediately**: In `run_source_inline`, classify errors properly — at least distinguish `TimeoutError`/`httpx.HTTPError`/`parse error` from the generic `Exception` handler. Store the error type alongside the error message.

3. **Build the probe**: Reuse the existing `/internal/connectors/probe` endpoint pattern. Create a script that iterates all 126 sources, calls `connector_for` + `fetch()` with a diagnostic timeout (30s), and outputs a structured GREEN/YELLOW/RED report.

4. **Triage RED sources first**: If a source can't even fetch, that's a showstopper. Either the URL is dead, the site has changed, or the connector type is wrong.

5. **For YELLOW sources**: Try adding `connector_config` JSON (declarative selectors via `ConfigurableHtmlConnector`) or fix the dedicated connector.

6. **Once the inventory is done**: Migrate working sources to the registry pattern as part of normal maintenance. Only then consider unifying the code paths.

### Risks

| Risk | Approach 1 | Approach 2 | Approach 3 |
|------|-----------|-----------|-----------|
| Breaking production sources | Low (probe is read-only) | High (refactoring 36 connectors) | Low |
| Missing architectural improvement | Medium (deferred to later) | Low (fixes everything) | High (never fixes) |
| Effort overrun | Low/Medium | High | Low |
| Team needs to learn connector internals | Medium | High | Low |
| 102 never-run sources may be dead | Low (probe reveals this) | High (refactoring dead code) | Low (still don't know) |
| Registry migration blocks on __init__ differences | Low (can migrate per-source) | High (must fix ALL signatures) | N/A |

### Specific Questions Answered

**1. What happens when POST /sources/run-all vs periodic sweep?**
- `run-all`: Sync endpoint → background daemon thread → ThreadPoolExecutor (max 2 workers) → each source runs in its own thread with its own event loop via `execute_source_run_locally`. Does NOT check for existing runs, does NOT check auto_paused, does NOT go through the dispatcher. Capped at 20 sources.
- Periodic sweep: Async → main event loop → `run_source` (dispatcher) → `run_source_inline`. Checks auto_paused, duplicate runs, runs stale recovery first. Sequential (not parallel).

**2. Why does the sync path exist alongside async?**
Legacy compatibility. `execute_source_run_locally` is a thin sync wrapper that creates a new event loop per call, needed by the synchronous FastAPI endpoints and the ThreadPoolExecutor in `run-all`. The async path (`run_source` → `run_source_inline`) is the newer modular extraction. Unifying them requires either making all endpoints async (feasible but touches every route) or changing the dispatcher to return a coroutine that callers can await.

**3. Error taxonomy?**
All errors → `except Exception` → `str(exc)`. No classification. `items_failed` is always 1 (per-run, not per-item). Only `asyncio.CancelledError` gets special treatment.

**4. How does the test suite mock?**
All external calls mocked (httpx, playwright). 48 test files use static HTML fixtures. No real URL hits in tests. Tests pass means "handles the mock HTML", not "works in production".

**5. Existing health monitoring?**
- Source model fields: `last_run_at`, `last_success_at`, `last_error`, `tier`, `auto_paused`, `consecutive_empty_runs`, `dom_hash`, `dom_hash_changed_at`, `last_item_count`, `selector_failures`
- SourceRun: `status`, `error_message`, `items_found/created/updated/failed`, `progress`, `logs`
- Alert model: for source_health events
- Health endpoint: `GET /sources/health` returns per-source `SourceHealthRead` with multi-metric score
- Auto-pause: after 3 consecutive empty runs or 3 consecutive selector failures

**6. Caching?**
Zero. No ETag, no If-Modified-Since, no local cache. DOM hash is computed but never used to skip re-fetching.

**7. Functional inventory — what would we need?**
- Use the existing `ConnectorProbeRequest` schema + `/internal/connectors/probe` logic
- Iterate all 126 sources, call `connector_for` + `connector.fetch()` + `connector.parse()`
- Classify: GREEN (content + candidates), YELLOW (content but no candidates), RED (exception)
- Store results in a new `SourceProbeResult` model or CSV
- Build a dashboard that shows the inventory (or just use `sources/health` with the new data)

### Ready for Proposal

**Yes**. The exploration reveals a clear picture. The proposal phase should:

1. Make the one-line fix to route `run-all` through the dispatcher
2. Add error type classification in `run_source_inline`
3. Design the functional inventory probe (CLI script or API extension)
4. Plan the triage workflow: probe → classify → fix (connector_config or new connector) → re-probe
5. Defer the code path unification until after the inventory
