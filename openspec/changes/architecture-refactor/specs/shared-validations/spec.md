# Shared Validations — Specification

## Purpose

Extract reusable validation logic currently scattered across services, routes, and Pydantic schemas into a dedicated `core/validators.py` module. Validators MUST be pure functions with no DB, network, or IO dependencies.

## Requirements

### Requirement: VAL-1 — Pure Validation Functions

Every extracted validator MUST be a pure function (no DB queries, no HTTP calls, no filesystem access).

#### Scenario: Date-range validation extracted
- GIVEN date-range checking logic in export and search routes
- WHEN extracted to `core/validators.py`
- THEN `validate_date_range(start: date, end: date) -> ValidationResult` exists
- AND a test calls it without importing FastAPI or SQLAlchemy

#### Scenario: URL format validation extracted
- GIVEN URL checks in `services.url_is_reachable()`
- WHEN extraction is applied
- THEN only pure checks (scheme, domain length, character validation) go to validators
- AND `url_is_reachable` stays in services since it performs HTTP IO

### Requirement: VAL-2 — Structured Results

Each validator MUST return a `ValidationResult(ok: bool, reason: str)` — not raise exceptions for normal validation failures.

#### Scenario: Invalid date range returns structured result
- GIVEN `validate_date_range(date(2025, 1, 1), date(2024, 1, 1))`
- WHEN called
- THEN it returns `ValidationResult(ok=False, reason="start_date after end_date")` without raising

#### Scenario: Valid input returns ok
- GIVEN `validate_date_range(date(2024, 1, 1), date(2025, 1, 1))`
- WHEN called
- THEN it returns `ValidationResult(ok=True, reason="")`

### Requirement: VAL-3 — Independent Testability

Validators MUST be testable without importing services, schemas, routes, or the DB session.

#### Scenario: Validator test needs no fixtures
- GIVEN `core/validators.py` with `validate_date_range`
- WHEN `pytest tests/test_validators.py` runs
- THEN it succeeds without a DB session, app instance, or async event loop
