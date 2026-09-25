"""T4 (fortalecer-201): visible quarantine + per-tier cohort metrics.

Pins the two T4 deliverables without touching scoring thresholds,
auto-pause thresholds, sweep cadence or the /metrics T2 contract:

- Quarantine: a noisy candidate and a duplicate candidate end up listed
  (with reason) in ``GET /sources/{id}/quarantine``. Persistence reuses
  the existing ``SourceRun.logs`` JSON column — no migration.
- Cohort: ``get_cohort_breakdown`` counts new opportunities per source
  tier (strategic/complementary/experimental) over trailing 7d/30d
  windows, and ``GET /dashboard/health`` carries it additively.

Runner tests use an isolated in-memory SQLite DB (same pattern as
``test_metrics_sweep.py``); endpoint tests go through the HTTP layer on
the shared test database with unique marker rows cleaned up afterwards.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import Base
from app.models import Opportunity, Organization, Role, Source, SourceRun, User
from app.services.quarantine import (
    QUARANTINE_REASONS,
    classify_validation_reason,
    extract_quarantine_items,
    quarantine_entry,
)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@pytest.fixture()
def db() -> Session:
    """Isolated in-memory session — hermetic by design."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _source(key: str, **kwargs) -> Source:
    defaults = {"name": key, "key": key, "base_url": "https://example.com/convocatorias"}
    defaults.update(kwargs)
    return Source(**defaults)


def _candidate(**kwargs) -> object:
    from app.connectors.base import OpportunityCandidate

    defaults = {
        "title": "Beca de investigación en salud pública",
        "entity": "Minciencias",
        "country": "Colombia",
        "official_url": None,
    }
    defaults.update(kwargs)
    return OpportunityCandidate(**defaults)


def _fake_connector(candidates: list, *, valid: bool = True, reason: str = "") -> object:
    """Minimal connector double for the runner's fetch/parse/validate calls."""
    from app.connectors.base import RawSourceResult, ValidationResult

    async def _fetch():
        return RawSourceResult(
            source_key="t4-test", url="https://example.com", content="<html></html>"
        )

    async def _parse(_raw):
        return list(candidates)

    async def _validate(_candidate):
        return ValidationResult(ok=valid, reason=reason)

    return SimpleNamespace(
        fetch=_fetch,
        parse=_parse,
        validate=_validate,
        get_updated_config=lambda: None,
    )


@pytest.fixture()
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force URL reachability checks to a fixed answer (no real HTTP)."""

    async def _reachable(_url: str) -> bool:
        return True

    monkeypatch.setattr("app.services.opportunity.async_url_is_reachable", _reachable)


@pytest.fixture()
def _patch_connector(monkeypatch: pytest.MonkeyPatch):
    """Patch the connector factory used inside runner._scrape_candidates."""

    def _install(connector: object) -> None:
        def _factory(*_args, **_kwargs):
            return connector

        monkeypatch.setattr("app.connectors.factory.connector_for", _factory)

    return _install


class TestQuarantineTaxonomy:
    def test_unknown_reason_falls_back_to_error(self) -> None:
        assert quarantine_entry("inventado", "t")["reason"] == "error"

    def test_known_reasons_preserved(self) -> None:
        for reason in QUARANTINE_REASONS:
            assert quarantine_entry(reason, "t")["reason"] == reason

    def test_classify_validation_reason(self) -> None:
        assert classify_validation_reason("URL unreachable (404)") == "url_muerta"
        assert classify_validation_reason("unsupported language: fr") == "idioma"
        assert classify_validation_reason("missing close_date") == "sin_fecha"
        assert classify_validation_reason("selector mismatch") == "validacion"
        assert classify_validation_reason(None) == "validacion"


class TestRunnerQuarantine:
    async def test_noise_candidate_listed_with_reason(
        self, db: Session, _no_network: None, _patch_connector
    ) -> None:
        """A noisy candidate must land in quarantine with motivo ruido."""
        from app.scraper.runner import run_source_inline

        source = _source("t4-noise-src")
        db.add(source)
        db.commit()

        noisy = _candidate(
            title="color: white background-color: #fff font-weight: bold",
            summary="display: flex justify-content: center",
        )
        _patch_connector(_fake_connector([noisy]))

        run = await run_source_inline(db, source)
        db.refresh(run)

        total, items = extract_quarantine_items([run])
        assert total >= 1
        reasons = {item["reason"] for item in items}
        assert "ruido" in reasons
        # Nothing persisted as an opportunity.
        assert db.scalar(select(Opportunity).where(Opportunity.source_id == source.id)) is None

    async def test_duplicate_candidate_listed_with_reason(
        self, db: Session, _no_network: None, _patch_connector
    ) -> None:
        """A candidate matching a known opportunity merges AND is listed."""
        from app.scraper.runner import run_source_inline

        source = _source("t4-dup-src")
        db.add(source)
        db.flush()
        db.add(
            Opportunity(
                source_id=source.id,
                external_id="ext-1",
                title="Beca de investigación en salud pública",
                slug="beca-salud-minciencias",
                entity="Minciencias",
                country="Colombia",
            )
        )
        db.commit()

        dupe = _candidate(external_id="ext-1")
        _patch_connector(_fake_connector([dupe]))

        run = await run_source_inline(db, source)
        db.refresh(run)

        total, items = extract_quarantine_items([run], reason="duplicado")
        assert total >= 1
        assert all(item["reason"] == "duplicado" for item in items)
        # Still a single opportunity row — the merge did not duplicate data.
        rows = db.scalars(select(Opportunity).where(Opportunity.source_id == source.id)).all()
        assert len(rows) == 1

    async def test_dead_url_candidate_listed_with_reason(
        self, db: Session, _patch_connector, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unreachable official_url is nulled AND recorded as url_muerta."""

        async def _unreachable(_url: str) -> bool:
            return False

        monkeypatch.setattr("app.services.opportunity.async_url_is_reachable", _unreachable)
        from app.scraper.runner import run_source_inline

        source = _source("t4-deadurl-src")
        db.add(source)
        db.commit()

        candidate = _candidate(official_url="https://example.com/convocatoria/1")
        _patch_connector(_fake_connector([candidate]))

        run = await run_source_inline(db, source)
        db.refresh(run)

        total, items = extract_quarantine_items([run], reason="url_muerta")
        assert total >= 1
        opp = db.scalar(select(Opportunity).where(Opportunity.source_id == source.id))
        assert opp is not None
        assert opp.official_url is None


class TestCohortBreakdown:
    def _seed_cohort(self, db: Session) -> Organization:
        org = Organization(name="t4-cohort", slug=f"t4-cohort-{uuid.uuid4().hex[:8]}")
        db.add(org)
        db.flush()
        now = _now()
        specs = [
            ("t4-strat", "strategic", [1, 2, 40]),
            ("t4-compl", "complementary", [3]),
            ("t4-exper", "experimental", [20]),
        ]
        for key, tier, ages in specs:
            source = _source(key, tier=tier)
            db.add(source)
            db.flush()
            for i, age in enumerate(ages):
                db.add(
                    Opportunity(
                        organization_id=org.id,
                        source_id=source.id,
                        title=f"{key} opp {i}",
                        slug=f"{key}-opp-{i}-{uuid.uuid4().hex[:6]}",
                        entity="Entidad",
                        country="Colombia",
                        created_at=now - timedelta(days=age),
                    )
                )
        db.commit()
        return org

    def test_counts_per_tier_and_window(self, db: Session) -> None:
        from app.services.analytics import get_cohort_breakdown

        org = self._seed_cohort(db)
        items = get_cohort_breakdown(db, org.id)
        counts = {(item.tier, item.period_days): item.new_opportunities for item in items}

        assert counts[("strategic", 7)] == 2
        assert counts[("strategic", 30)] == 2
        assert counts[("complementary", 7)] == 1
        assert counts[("complementary", 30)] == 1
        assert counts[("experimental", 7)] == 0
        assert counts[("experimental", 30)] == 1

    def test_includes_all_tiers_even_when_empty(self, db: Session) -> None:
        from app.services.analytics import get_cohort_breakdown

        org = Organization(name="t4-empty", slug=f"t4-empty-{uuid.uuid4().hex[:8]}")
        db.add(org)
        db.commit()

        items = get_cohort_breakdown(db, org.id)
        tiers_7d = {item.tier for item in items if item.period_days == 7}
        assert {"strategic", "complementary", "experimental"} <= tiers_7d
        assert all(item.new_opportunities == 0 for item in items)


# ---------------------------------------------------------------------------
# HTTP layer (shared test database, unique markers, cleanup afterwards)
# ---------------------------------------------------------------------------


def _client_with_admin() -> TestClient:
    from app.core.security import create_access_token, hash_password
    from app.db.seed import seed
    from app.db.session import SessionLocal
    from app.main import app

    seed()
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert org is not None
        if not db.scalar(select(User).where(User.email == "admin@convocaradar.io")):
            db.add(
                User(
                    email="admin@convocaradar.io",
                    name="Admin",
                    password_hash=hash_password("ConvocaRadarLocal123!"),
                    role=Role.admin.value,
                    organization_id=org.id,
                )
            )
            db.commit()
        admin = db.scalar(select(User).where(User.email == "admin@convocaradar.io"))
        admin_id = str(admin.id)
    finally:
        db.close()
    token = create_access_token(admin_id, extra={"scope": "access", "password_changed_at": 0})
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {token}"
    return client


@pytest.fixture()
def quarantine_run_ids() -> list:
    ids: list = []
    yield ids
    from app.db.session import SessionLocal

    session = SessionLocal()
    try:
        for run_id, source_id in ids:
            session.execute(SourceRun.__table__.delete().where(SourceRun.id == run_id))
            session.execute(Source.__table__.delete().where(Source.id == source_id))
        session.commit()
    finally:
        session.close()


class TestQuarantineEndpoint:
    def test_lists_discards_with_reason(self, quarantine_run_ids: list) -> None:
        from app.db.session import SessionLocal

        marker = uuid.uuid4().hex[:8]
        client = _client_with_admin()
        session = SessionLocal()
        try:
            org = session.scalar(
                select(Organization).where(Organization.slug == "convocaradar-local")
            )
            source = Source(
                organization_id=org.id,
                name=f"t4-q-{marker}",
                key=f"t4-q-{marker}",
                base_url="https://example.com",
            )
            session.add(source)
            session.flush()
            run = SourceRun(
                source_id=source.id,
                status="success",
                started_at=_now(),
                finished_at=_now(),
                items_found=1,
                logs=[
                    quarantine_entry("ruido", "color: white banner", url="https://example.com/x"),
                    quarantine_entry(
                        "duplicado", "Beca repetida", detail="merged into opportunity 1"
                    ),
                    {"level": "info", "message": "not quarantine"},
                ],
            )
            session.add(run)
            session.commit()
            source_id, run_id = source.id, run.id
            quarantine_run_ids.append((run_id, source_id))
        finally:
            session.close()

        response = client.get(f"/api/v1/sources/{source_id}/quarantine")
        assert response.status_code == 200
        body = response.json()
        assert body["source_id"] == source_id
        assert body["total"] == 2
        assert {item["reason"] for item in body["items"]} == {"ruido", "duplicado"}

        filtered = client.get(f"/api/v1/sources/{source_id}/quarantine", params={"reason": "ruido"})
        assert filtered.status_code == 200
        assert filtered.json()["total"] == 1

        bad = client.get(f"/api/v1/sources/{source_id}/quarantine", params={"reason": "nope"})
        assert bad.status_code == 400


class TestHealthCohortShape:
    def test_health_carries_cohort_breakdown_additively(self) -> None:
        client = _client_with_admin()
        response = client.get("/api/v1/dashboard/health")
        assert response.status_code == 200
        body = response.json()
        # Legacy shape intact.
        for key in (
            "kpis",
            "status_breakdown",
            "country_breakdown",
            "data_coverage",
            "sources_health",
        ):
            assert key in body
        # New additive field.
        assert isinstance(body["cohort_breakdown"], list)
        for item in body["cohort_breakdown"]:
            assert set(item) >= {"tier", "period_days", "new_opportunities"}
