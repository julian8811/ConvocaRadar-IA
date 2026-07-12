# Change D — Discovery/Detail Separation + DOM Change Detection

## Review Workload Forecast

- **400-line budget risk**: High
- **Chained PRs recommended**: No (single PR, already on branch)
- **Decision needed before apply**: No

## Phase 1: DOM Monitor Utility

- [x] 1.1 Create `app/scraper/dom_monitor.py` with `compute_dom_hash()`
- [x] 1.2 Add `detect_structural_change()` function
- [x] 1.3 Add HTML normalization helpers (strip scripts, styles, dynamic content)

## Phase 2: Source Model Changes

- [x] 2.1 Add `dom_hash`, `dom_hash_changed_at`, `last_item_count`, `selector_failures` fields to `Source` model

## Phase 3: ConfigurableHtmlConnector Diagnostics

- [x] 3.1 Track which selectors succeeded in configurable_html parse
- [x] 3.2 Return selector diagnostics from parse (via selector_diagnostics property)

## Phase 4: Two-Phase Runner

- [x] 4.1 Update `run_source_inline` to do Phase 1 Discovery (list page only)
- [x] 4.2 Add Phase 2 Detail (only fetch changed/new items)
- [x] 4.3 Update `Source.dom_hash` after scrape
- [x] 4.4 Log structural changes to `SourceRun.logs`

## Phase 5: Selector Failure Tracking

- [x] 5.1 Track `selector_failures` in runner
- [x] 5.2 Auto-pause source after 3 consecutive selector failures
