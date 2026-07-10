# Connector Registry — Specification

## Purpose

Replace the 40+ if-elif chain in `connectors/factory.py` with a declarative registry pattern where connectors self-register by source type at import time.

## Requirements

### Requirement: REG-1 — Registry with register/get

The system MUST provide a `ConnectorRegistry` class with `register(cls)` and `get(source_type: str) -> type` methods. `get` MUST raise `KeyError` for unregistered types.

#### Scenario: Connector registered via decorator
- GIVEN a connector class `WordPressGrantsConnector` with `source_key = "wordpress-grants"`
- WHEN `@registry.register` is applied
- THEN `registry.get("wordpress-grants")` returns the class
- AND `registry.get("nonexistent")` raises `KeyError`

#### Scenario: Decorator works on any SourceConnector
- GIVEN any class matching `SourceConnector` protocol
- WHEN `@registry.register` is applied
- THEN `registry.list_sources()` includes its `source_key`

### Requirement: REG-2 — Import-Time Registration

Registration MUST happen at import time. Importing a connector module is sufficient — no manual `factory.py` edits.

#### Scenario: New connector auto-registers
- GIVEN a new `connectors/new_source.py` with `@registry.register`
- WHEN `from app.connectors import new_source` runs
- THEN `registry.get("new-source")` resolves without editing `factory.py`

#### Scenario: All existing connectors register
- GIVEN all modules in `connectors/` imported
- WHEN `registry.list_sources()` is called
- THEN it returns all 40+ source keys previously handled by `connector_for()`

### Requirement: REG-3 — Factory Function Retained as Facade

The `connector_for()` function MUST remain as a thin facade over the registry for backward compatibility, but MUST delegate to `registry.get()` internally.

#### Scenario: connector_for delegates to registry
- GIVEN a call to `connector_for("grants-gov")`
- WHEN the registry has `grants-gov` registered
- THEN the result is identical to `registry.get("grants-gov")`
- AND no if-elif chain is consulted
