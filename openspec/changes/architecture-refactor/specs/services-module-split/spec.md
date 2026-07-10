# Services Module Split — Specification

## Purpose

Split `apps/api/app/services.py` (~1600+ lines) into single-responsibility modules organized by concern, preserving all existing behavior through backward-compatible re-exports.

## Requirements

### Requirement: SRP-1 — Single Responsibility Projections

The services module MUST be split into one file per concern: scoring, dedup, export, search, and LLM orchestration. Each module MUST import only from `core/`, `db/`, `models/`, or `connectors/` — never from sibling service modules (no cross-concern coupling).

#### Scenario: Scoring extracted as standalone module
- GIVEN the monolithic `services.py` with `score_opportunity()` and `reanalyze_opportunity()`
- WHEN the split is applied
- THEN `apps/api/app/services/scoring.py` exists with all scoring functions
- AND scoring functions remain callable from `apps.api.app.services`

#### Scenario: Dedup extracted independently
- GIVEN dedup functions in `services.py`
- WHEN the split is applied
- THEN `apps/api/app/services/dedup.py` exists
- AND it does not import from scoring or export modules

### Requirement: SRP-2 — No Circular Imports

The split MUST NOT introduce circular imports among the new service modules.

#### Scenario: Import graph verified acyclic
- GIVEN the new `services/` directory with 5+ modules
- WHEN the module import graph is analyzed
- THEN there is no path of imports that creates a cycle
- AND `python -c "from app.services import *"` succeeds without `ImportError`

### Requirement: SRP-3 — Backward-Compatible Re-exports

A `services/__init__.py` MUST re-export every public symbol so all existing callers (routes, CLI, seed scripts) import without changes.

#### Scenario: Route imports remain unchanged
- GIVEN a route importing `from app.services import execute_source_run_locally`
- WHEN the split is applied
- THEN the same import resolves correctly
- AND the function behaves identically

### Requirement: SRP-4 — Typed Signatures

Each extracted module MUST declare typed function signatures — no `**kwargs` passthrough or `Any`-typed parameters for known inputs.

#### Scenario: New module has typed functions
- GIVEN the extracted `search.py` module
- WHEN `mypy` is run on it
- THEN no `type-arg` or `no-any-return` errors for public function signatures
