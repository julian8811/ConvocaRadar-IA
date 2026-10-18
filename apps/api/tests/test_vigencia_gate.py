"""T2 (vigencia): central gate rejects candidates without a future close_date.

S1/S3: no se registran convocatorias sin vigencia verificada con fecha de
cierre. The gate runs inside ``_scrape_candidates`` after pilot detail
enrichment + connector validate (post-enrichment by construction), before
append: missing close_date or past close_date → rejected with quarantine
reason ``sin_fecha`` (classifier maps the deadline marker) + stats counter
``vigencia_rejected``. LLM payload enrichment downstream never sees them
(dates-by-LLM proved unreliable: phantom funding/dates, L4 падение).

RED: fails while the gate does not exist (all three dated cases persist).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import Base
from app.models import Source


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _source(key: str) -> Source:
    return Source(name=key, key=key, base_url="https://example.com/convocatorias")


def _candidate(title: str, close_date) -> object:
    from app.connectors.base import OpportunityCandidate

    return OpportunityCandidate(
        title=title,
        entity="Test Entity",
        country="Colombia",
        official_url="https://example.com/convocatoria-x",
        summary="Apoyo a proyectos productivos con cofinanciacion amplia del programa.",
        close_date=close_date,
    )


def _fake_connector(candidates: list) -> object:
    from app.connectors.base import RawSourceResult, ValidationResult

    async def _fetch():
        return RawSourceResult(
            source_key="t2-test", url="https://example.com", content="<html></html>"
        )

    async def _parse(_raw):
        return list(candidates)

    async def _validate(_candidate):
        return ValidationResult(ok=True)

    return SimpleNamespace(
        fetch=_fetch,
        parse=_parse,
        validate=_validate,
        get_updated_config=lambda: None,
    )


@pytest.fixture()
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _reachable(_url: str) -> bool:
        return True

    # El runner enlaza async_url_is_reachable desde app.services.validation
    # (import en cuerpo de _warm_url_cache); el namespace opportunity no rige.
    monkeypatch.setattr("app.services.validation.async_url_is_reachable", _reachable)
    monkeypatch.setattr("app.services.opportunity.async_url_is_reachable", _reachable)


@pytest.fixture()
def _patch_connector(monkeypatch: pytest.MonkeyPatch):
    def _install(connector: object) -> None:
        def _factory(*_args, **_kwargs):
            return connector

        monkeypatch.setattr("app.connectors.factory.connector_for", _factory)

    return _install


async def _run(db: Session, connector: object, monkeypatch) -> tuple[list, dict]:
    from app.scraper import runner as runner_module

    def _factory(*_args, **_kwargs):
        return connector

    monkeypatch.setattr("app.connectors.factory.connector_for", _factory)
    source = _source("t2-gate-src")
    db.add(source)
    db.commit()
    stats: dict = {}
    opportunities = await runner_module._scrape_candidates(source, stats)
    return opportunities, stats


class TestVigenciaGate:
    async def test_future_close_passes(self, db, _no_network, monkeypatch):
        future = _candidate("Convocatoria fondo 2027", _now() + timedelta(days=60))
        opportunities, _ = await _run(db, _fake_connector([future]), monkeypatch)
        assert len(opportunities) == 1

    async def test_missing_close_rejected_with_quarantine(self, db, _no_network, monkeypatch):
        nodate = _candidate("Convocatoria sin fecha", None)
        opportunities, stats = await _run(db, _fake_connector([nodate]), monkeypatch)
        assert opportunities == []
        assert stats.get("vigencia_rejected") == 1
        reasons = [q.get("reason") for q in stats.get("quarantine", [])]
        assert "sin_fecha" in reasons

    async def test_past_close_rejected(self, db, _no_network, monkeypatch):
        old = _candidate("Convocatoria 2021", _now() - timedelta(days=30))
        opportunities, stats = await _run(db, _fake_connector([old]), monkeypatch)
        assert opportunities == []
        assert stats.get("vigencia_rejected") == 1

    async def test_gate_counts_alongside_validation(self, db, _no_network, monkeypatch):
        mixed = [
            _candidate("Futura", _now() + timedelta(days=10)),
            _candidate("Sin fecha", None),
            _candidate("Vencida", _now() - timedelta(days=5)),
        ]
        opportunities, stats = await _run(db, _fake_connector(mixed), monkeypatch)
        assert len(opportunities) == 1
        assert stats.get("vigencia_rejected") == 2
