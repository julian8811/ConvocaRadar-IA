import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

os.environ["DATABASE_URL"] = "sqlite:///./test_convocaradar.db"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["STORAGE_DIR"] = "./test_storage"
os.environ["SMTP_HOST"] = ""
os.environ["INTERNAL_API_KEY"] = "test_internal_key"

Path("test_convocaradar.db").unlink(missing_ok=True)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db.seed import seed  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.core.ai import EMBEDDING_MODEL_VERSION  # noqa: E402
import app.main as app_main  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Alert, Opportunity, OpportunityEmbedding, OpportunityScore, Organization, Source, SourceRun, Task  # noqa: E402
from app.schemas import OpportunityCreate  # noqa: E402
from app.services import create_opportunity, is_private_url  # noqa: E402


def client() -> TestClient:
    seed()
    return TestClient(app)


def token(c: TestClient) -> str:
    response = c.post(
        "/api/v1/auth/login",
        json={"email": "admin@convocaradar.io", "password": "ConvocaRadarLocal123!"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def create_fixture_opportunity(*, close_days: int = 30) -> str:
    db = SessionLocal()
    try:
        organization = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert organization is not None
        source = db.scalar(select(Source).where(Source.key == "grants-gov"))
        assert source is not None
        opportunity = create_opportunity(
            db,
            OpportunityCreate(
                source_id=source.id,
                external_id="fixture-grants-2026",
                title="Convocatoria piloto de cooperacion 2026",
                entity="Grants.gov",
                country="United States",
                categories=["grants", "research"],
                topics=["innovation", "cooperation"],
                summary="Oportunidad de prueba creada para validar el flujo real de la API.",
                raw_text="Fixture real de pruebas sin marca ficticia.",
                official_url="https://www.grants.gov/search-results-detail/fixture-grants-2026",
                close_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=close_days),
                funding_amount_value=250000,
                funding_amount_currency="USD",
                funding_amount_raw="USD 250,000",
                eligible_applicants=["university", "research_group"],
                requirements=["Concept note"],
                documents_required=["Proposal"],
                evaluation_criteria=["Impact", "Feasibility"],
                confidence_score=0.9,
            ),
            organization_id=organization.id,
        )
        db.commit()
        db.refresh(opportunity)
        return opportunity.id
    finally:
        db.close()


def test_login_and_me() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    response = c.get("/api/v1/me", headers=auth)
    assert response.status_code == 200
    assert response.json()["email"] == "admin@convocaradar.io"


def test_opportunities_and_score() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    opportunity_id = create_fixture_opportunity()
    response = c.get("/api/v1/opportunities", headers=auth)
    assert response.status_code == 200
    items = response.json()["items"]
    assert items
    db = SessionLocal()
    try:
        auto_scores = list(db.scalars(select(OpportunityScore).where(OpportunityScore.opportunity_id == opportunity_id)))
    finally:
        db.close()
    assert auto_scores
    score = c.post(f"/api/v1/opportunities/{items[0]['id']}/scores", headers=auth)
    assert score.status_code == 200
    assert score.json()["priority"] in {"high", "medium", "low", "not_recommended"}


def test_semantic_search_returns_best_match() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    opportunity_id = create_fixture_opportunity()
    response = c.get("/api/v1/opportunities/semantic-search?query=research%20innovation%20grant", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"]
    assert payload["items"][0]["opportunity"]["id"] == opportunity_id
    assert payload["items"][0]["similarity"] > 0

    db = SessionLocal()
    try:
        embedding = db.scalar(select(OpportunityEmbedding).where(OpportunityEmbedding.opportunity_id == opportunity_id))
    finally:
        db.close()
    assert embedding is not None
    assert embedding.embedding


def test_text_search_matches_description_and_summary() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    opportunity_id = create_fixture_opportunity()
    response = c.get("/api/v1/opportunities?search=prueba%20creada%20para%20validar", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    assert any(item["id"] == opportunity_id for item in payload["items"])


def test_reanalyze_opportunity_improves_payload() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    db = SessionLocal()
    try:
        organization = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        source = db.scalar(select(Source).where(Source.key == "grants-gov"))
        assert organization is not None and source is not None
        opportunity = create_opportunity(
            db,
            OpportunityCreate(
                source_id=source.id,
                external_id="reanalyze-fixture",
                title="Open Call Fixture",
                entity="Entidad por validar",
                country="Por validar",
                raw_text=(
                    "Open call for research and innovation projects in Colombia. "
                    "Close date 2026-12-01. Documents: proposal, budget, CV. "
                    "Requirements: university or research group."
                ),
                official_url="https://example.com/reanalyze-fixture",
                confidence_score=0.2,
            ),
            organization_id=organization.id,
        )
        db.commit()
        db.refresh(opportunity)
        opportunity_id = opportunity.id
    finally:
        db.close()

    response = c.post(f"/api/v1/opportunities/{opportunity_id}/reanalyze?force=true", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    assert payload["country"] == "Colombia"
    assert payload["summary"]
    assert payload["requirements"]
    assert payload["confidence_score"] >= 0.2


def test_bulk_reanalyze_opportunities() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    opportunity_id = create_fixture_opportunity()
    response = c.post("/api/v1/opportunities/reanalyze-all?force=true&limit=25", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    assert payload["processed"] >= 1
    assert payload["rescored"] >= 1

    db = SessionLocal()
    try:
        embedding = db.scalar(select(OpportunityEmbedding).where(OpportunityEmbedding.opportunity_id == opportunity_id))
    finally:
        db.close()
    assert embedding is not None


def test_seed_includes_real_sources() -> None:
    seed()
    seed()
    db = SessionLocal()
    try:
        apc = list(db.scalars(select(Source).where(Source.key == "apc-colombia")))
        eu = list(db.scalars(select(Source).where(Source.key == "eu-funding-tenders")))
        local_user = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
    finally:
        db.close()
    assert len(apc) == 1
    assert len(eu) == 1
    assert local_user is not None


def test_seed_includes_grants_gov_source() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    response = c.get("/api/v1/sources", headers=auth)
    assert response.status_code == 200
    grants = [item for item in response.json() if item["key"] == "grants-gov"]
    assert grants
    assert grants[0]["source_type"] == "api"
    assert grants[0]["base_url"] == "https://api.grants.gov/v1/api/search2"
    simpler = [item for item in response.json() if item["key"] == "simpler-grants"]
    assert simpler
    assert simpler[0]["base_url"] == "https://simpler.grants.gov/search"
    grants_rss = [item for item in response.json() if item["key"] == "grants-gov-rss"]
    assert grants_rss
    assert grants_rss[0]["source_type"] == "rss"
    nsf_rss = [item for item in response.json() if item["key"] == "nsf-funding-rss"]
    assert nsf_rss
    assert nsf_rss[0]["base_url"] == "https://www.nsf.gov/rss/rss_www_funding_pgm_annc_inf.xml"
    nsf = [item for item in response.json() if item["key"] == "nsf-funding"]
    assert nsf
    ukri = [item for item in response.json() if item["key"] == "ukri-opportunities"]
    assert ukri
    unesco = [item for item in response.json() if item["key"] == "unesco-call-for-proposals"]
    assert unesco
    minciencias = [item for item in response.json() if item["key"] == "minciencias"]
    assert minciencias
    assert minciencias[0]["country"] == "Colombia"
    icetex = [item for item in response.json() if item["key"] == "icetex-vigentes"]
    assert icetex
    assert icetex[0]["base_url"] == "https://web.icetex.gov.co/becas/becas-para-estudios-en-el-exterior/becas-vigentes"
    men = [item for item in response.json() if item["key"] == "mineducacion-becas"]
    assert men
    innovamos = [item for item in response.json() if item["key"] == "innovamos-global-innovation-fund"]
    assert innovamos
    undef = [item for item in response.json() if item["key"] == "undef"]
    assert undef
    innpulsa = [item for item in response.json() if item["key"] == "innpulsa"]
    assert innpulsa
    assert innpulsa[0]["source_type"] == "api"
    assert innpulsa[0]["base_url"] == "https://convocatorias.innpulsacolombia.com/api/convocatorias?active_only=true&include_private=false&include_archive=false"
    apc = [item for item in response.json() if item["key"] == "apc-colombia"]
    assert apc
    eu = [item for item in response.json() if item["key"] == "eu-funding-tenders"]
    assert eu


def test_sources_health_endpoint() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    response = c.get("/api/v1/sources/health", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    assert payload
    source_health = [item for item in payload if item["key"] == "grants-gov"]
    assert source_health
    assert source_health[0]["status"] in {"healthy", "degraded", "failing", "idle"}
    assert "recent_runs" in source_health[0]
    assert "success_rate" in source_health[0]
    assert "average_items_found" in source_health[0]


def test_opportunity_document_lifecycle() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    opportunity_id = create_fixture_opportunity()

    upload = c.post(
        f"/api/v1/opportunities/{opportunity_id}/documents",
        headers=auth,
        files={"file": ("guia.txt", b"Documento de prueba", "text/plain")},
    )
    assert upload.status_code == 200
    document_id = upload.json()["id"]
    assert upload.json()["file_name"] == "guia.txt"
    assert Path(upload.json()["storage_path"]).exists()

    documents = c.get(f"/api/v1/opportunities/{opportunity_id}/documents", headers=auth)
    assert documents.status_code == 200
    assert any(item["id"] == document_id for item in documents.json())

    download = c.get(f"/api/v1/opportunity-documents/{document_id}/download", headers=auth)
    assert download.status_code == 200
    assert download.content == b"Documento de prueba"

    delete = c.delete(f"/api/v1/opportunity-documents/{document_id}", headers=auth)
    assert delete.status_code == 204


def test_create_source_rejects_private_url() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    response = c.post(
        "/api/v1/sources",
        headers=auth,
        json={
            "name": "Localhost",
            "key": "localhost",
            "base_url": "http://127.0.0.1:8080",
            "allowed_domains": ["127.0.0.1"],
        },
    )
    assert response.status_code == 400
    assert is_private_url("http://127.0.0.1:8080")


def test_create_source_rejects_private_tld_url() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    response = c.post(
        "/api/v1/sources",
        headers=auth,
        json={
            "name": "Local host",
            "key": "local-host",
            "base_url": "http://portal.internal",
            "allowed_domains": ["portal.internal"],
        },
    )
    assert response.status_code == 400
    assert is_private_url("http://portal.internal")


def test_rate_limit_blocks_repeated_requests(monkeypatch) -> None:
    c = client()
    monkeypatch.setattr(app_main.settings, "rate_limit_requests_per_minute", 1)
    app_main.app.state.rate_limits.clear()
    first = c.post("/api/v1/auth/login", json={"email": "admin@convocaradar.io", "password": "ConvocaRadarLocal123!"})
    assert first.status_code == 200
    second = c.post("/api/v1/auth/login", json={"email": "admin@convocaradar.io", "password": "ConvocaRadarLocal123!"})
    assert second.status_code == 429


def test_report_creation() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    create_fixture_opportunity()
    response = c.post("/api/v1/reports", headers=auth, json={"title": "Reporte institucional", "format": "html"})
    assert response.status_code == 200
    html = response.json()["html_content"]
    assert "ConvocaRadar IA" in html
    assert "Resumen ejecutivo" in html
    assert "link-button" in html
    assert 'href="https://www.grants.gov/search-results-detail/fixture-grants-2026"' in html
    assert "Formato listo para lectura ejecutiva" in html

def test_ai_structured_extraction_and_scoring() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    response = c.post(
        "/api/v1/ai/extract-opportunity",
        headers=auth,
        json={
            "text": (
                "Open call for research and innovation projects in Colombia. "
                "Close date 2026-12-01. Documents: proposal, budget, CV. "
                "Requirements: university or research group."
            )
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["title"]
    assert "research" in payload["category"] or "innovation" in payload["category"]
    assert payload["priority"] in {"high", "medium", "low", "not_recommended"}
    assert payload["model_version"] == "local-heuristic-v2"
    assert payload["prompt_version"] == "structured-extraction-v3"
    assert payload["extraction_strategy"] in {"local-heuristic", "remote-llm"}
    assert payload["provider"]

    score = c.post(
        "/api/v1/ai/score-opportunity",
        headers=auth,
        json={
            "text": (
                "Open call for research and innovation projects in Colombia. "
                "Close date 2026-12-01. Documents: proposal, budget, CV."
            )
        },
    )
    assert score.status_code == 200
    assert score.json()["score"] >= 50


def test_ai_structured_extraction_ignores_scraping_noise() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    response = c.post(
        "/api/v1/ai/extract-opportunity",
        headers=auth,
        json={
            "text": """
            <style>
              a { color: white; }
              .box-address { display: flex; justify-content: center; }
            </style>
            UNESCO Call for Proposals 2027
            International call for proposals in education and science.
            Deadline April 8, 2027.
            """,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "UNESCO Call for Proposals 2027"
    assert "color:" not in payload["summary"]
    assert payload["summary"]
    assert payload["confidence"] >= 0.5


def test_create_opportunity_enriches_incomplete_payload() -> None:
    db = SessionLocal()
    try:
        organization = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        source = db.scalar(select(Source).where(Source.key == "grants-gov"))
        assert organization is not None and source is not None
        opportunity = create_opportunity(
            db,
            OpportunityCreate(
                source_id=source.id,
                external_id="ai-enrichment-fixture",
                title="AI enrichment fixture",
                entity="Entidad por validar",
                country="Por validar",
                raw_text=(
                    "Open call for research and innovation projects in Colombia. "
                    "Close date 2026-12-01. Documents: proposal, budget, CV. "
                    "Requirements: university or research group."
                ),
                official_url="https://example.com/ai-enrichment-fixture",
                confidence_score=0.35,
            ),
            organization_id=organization.id,
        )
        db.commit()
        db.refresh(opportunity)
    finally:
        db.close()

    assert opportunity.categories
    assert opportunity.requirements
    assert opportunity.summary
    assert opportunity.country == "Colombia"
    assert opportunity.close_date is not None
    assert opportunity.confidence_score >= 0.35


def test_create_opportunity_rejects_noise_title() -> None:
    db = SessionLocal()
    try:
        organization = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        source = db.scalar(select(Source).where(Source.key == "grants-gov"))
        assert organization is not None and source is not None
        with pytest.raises(ValueError, match="scraping noise"):
            create_opportunity(
                db,
                OpportunityCreate(
                    source_id=source.id,
                    external_id="noise-fixture",
                    title="a { color: white; }",
                    entity="Entidad por validar",
                    country="Por validar",
                    raw_text="body { display: flex; }",
                    summary="font-weight: bold;",
                    official_url="https://example.com/noise-fixture",
                ),
                organization_id=organization.id,
            )
    finally:
        db.close()


def test_xlsx_report_download() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    response = c.post("/api/v1/reports", headers=auth, json={"title": "Reporte xlsx", "format": "xlsx"})
    assert response.status_code == 200
    report_id = response.json()["id"]
    download = c.get(f"/api/v1/reports/{report_id}/download", headers=auth)
    assert download.status_code == 200
    assert download.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert download.content[:2] == b"PK"
    stored = c.get(f"/api/v1/reports/{report_id}", headers=auth)
    assert stored.status_code == 200
    assert Path(stored.json()["file_path"]).exists()


def test_pdf_report_download_and_regenerate() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    response = c.post(
        "/api/v1/reports",
        headers=auth,
        json={"title": "Reporte pdf", "format": "pdf", "filters": {"country": "Colombia"}},
    )
    assert response.status_code == 200
    report_id = response.json()["id"]
    regenerated = c.post(f"/api/v1/reports/{report_id}/regenerate", headers=auth)
    assert regenerated.status_code == 200
    download = c.get(f"/api/v1/reports/{report_id}/download", headers=auth)
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/pdf")
    assert download.content[:4] == b"%PDF"
    stored = c.get(f"/api/v1/reports/{report_id}", headers=auth)
    assert stored.status_code == 200
    assert Path(stored.json()["file_path"]).exists()


def test_source_run_creates_real_opportunity_via_connector(monkeypatch) -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    from app import services as app_services

    class StubConnector:
        source_key = "grants-gov"

        async def fetch(self):
            return type(
                "Raw",
                (),
                {
                    "source_key": "grants-gov",
                    "url": "https://www.grants.gov/search-results-detail/fixture-grants-2026",
                    "content": "<article><a href='/search-results-detail/fixture-grants-2026'>Research Cooperation Call 2026</a><p>Open. Deadline March 10, 2026. USD 250,000.</p></article>",
                    "content_type": "text/html",
                },
            )()

        async def parse(self, raw):
            from worker.connectors.base import OpportunityCandidate

            return [
                OpportunityCandidate(
                    title="Research Cooperation Call 2026",
                    entity="Grants.gov",
                    country="United States",
                    official_url=raw.url,
                    summary="Open. Deadline March 10, 2026.",
                    categories=["grants", "research"],
                    topics=["cooperation"],
                    requirements=["Concept note"],
                    raw_text="Open. Deadline March 10, 2026. USD 250,000.",
                    confidence_score=0.93,
                    close_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=30),
                    funding_amount_raw="USD 250,000",
                )
            ]

        async def validate(self, candidate):
            from worker.connectors.base import ValidationResult

            return ValidationResult(ok=True)

    monkeypatch.setattr(app_services, "connector_for", lambda *_args, **_kwargs: StubConnector())
    sources = c.get("/api/v1/sources", headers=auth)
    assert sources.status_code == 200
    source_id = [item for item in sources.json() if item["key"] == "grants-gov"][0]["id"]
    run = c.post(f"/api/v1/sources/{source_id}/run", headers=auth)
    assert run.status_code == 200
    payload = run.json()
    assert payload["status"] == "success"
    assert payload["items_found"] == 1
    assert any(log["message"] == "Local connector executed" for log in payload["logs"])
    opportunities = c.get("/api/v1/opportunities?search=Research%20Cooperation%20Call%202026", headers=auth)
    assert opportunities.status_code == 200
    assert opportunities.json()["total"] >= 1
    tasks = c.get("/api/v1/tasks", headers=auth)
    assert tasks.status_code == 200
    assert any(item["source_run_id"] == payload["id"] and item["status"] == "success" for item in tasks.json())


def test_internal_scheduler_requires_key() -> None:
    c = client()
    response = c.post("/api/v1/internal/scheduler/sources/run-enabled", headers={"X-Internal-API-Key": "wrong"})
    assert response.status_code == 401


def test_internal_scheduler_runs_enabled_sources(monkeypatch) -> None:
    c = client()
    from app import services as app_services

    class StubConnector:
        source_key = "grants-gov"

        async def fetch(self):
            return type(
                "Raw",
                (),
                {
                    "source_key": "grants-gov",
                    "url": "https://www.grants.gov/search-results-detail/fixture-grants-2026",
                    "content": "<article><a href='/search-results-detail/fixture-grants-2026'>Research Cooperation Call 2026</a></article>",
                    "content_type": "text/html",
                },
            )()

        async def parse(self, raw):
            from worker.connectors.base import OpportunityCandidate

            return [
                OpportunityCandidate(
                    title="Research Cooperation Call 2026",
                    entity="Grants.gov",
                    country="United States",
                    official_url=raw.url,
                    confidence_score=0.9,
                )
            ]

        async def validate(self, candidate):
            from worker.connectors.base import ValidationResult

            return ValidationResult(ok=True)

    monkeypatch.setattr(app_services, "connector_for", lambda *_args, **_kwargs: StubConnector())
    response = c.post(
        "/api/v1/internal/scheduler/sources/run-enabled",
        headers={"X-Internal-API-Key": "test_internal_key"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["sources_checked"] >= 1
    assert payload["runs_created"] >= 1


def test_internal_source_run_completion_creates_opportunity() -> None:
    c = client()
    db = SessionLocal()
    try:
        source = db.scalar(select(Source).where(Source.key == "grants-gov"))
        assert source is not None
        run = SourceRun(source_id=source.id, status="queued", logs=[])
        db.add(run)
        db.flush()
        task = Task(
            organization_id=source.organization_id,
            source_run_id=run.id,
            task_type="scrape_source",
            provider="celery",
            status="queued",
            payload={"source_key": source.key},
        )
        db.add(task)
        db.commit()
        run_id = run.id
        task_id = task.id
    finally:
        db.close()


def test_failed_source_run_creates_health_alert() -> None:
    c = client()
    db = SessionLocal()
    try:
        source = db.scalar(select(Source).where(Source.key == "grants-gov"))
        assert source is not None
        run = SourceRun(source_id=source.id, status="queued", logs=[])
        db.add(run)
        task = Task(
            organization_id=source.organization_id,
            source_run_id=run.id,
            task_type="scrape_source",
            provider="celery",
            status="queued",
            payload={"source_key": source.key},
        )
        db.add(task)
        db.commit()
        run_id = run.id
        task_id = task.id
    finally:
        db.close()

    response = c.post(
        f"/api/v1/internal/source-runs/{run_id}/complete",
        headers={"X-Internal-API-Key": "test_internal_key"},
        json={
            "task_id": task_id,
            "status": "failed",
            "items_found": 0,
            "items_valid": 0,
            "items_invalid": 0,
            "items": [],
            "error_message": "HTTP 500 from source",
        },
    )
    assert response.status_code == 200
    db = SessionLocal()
    try:
        alerts = list(db.scalars(select(Alert).where(Alert.alert_type == "source_health")))
    finally:
        db.close()
    assert alerts
    assert any("grants-gov" in alert.message for alert in alerts)


def test_retry_degraded_sources_schedules_retry(monkeypatch) -> None:
    c = client()
    import app.api.v1.internal as internal_api

    monkeypatch.setattr(internal_api, "enqueue_scrape_source", lambda *args, **kwargs: "celery-retry-123")
    db = SessionLocal()
    try:
        source = db.scalar(select(Source).where(Source.key == "grants-gov"))
        assert source is not None
        task_ids = list(
            db.scalars(
                select(Task.id)
                .join(SourceRun, SourceRun.id == Task.source_run_id)
                .where(SourceRun.source_id == source.id)
            )
        )
        if task_ids:
            db.query(Task).filter(Task.id.in_(task_ids)).delete(synchronize_session=False)
        run = SourceRun(source_id=source.id, status="failed", items_found=0, items_created=0, items_updated=0, logs=[])
        db.add(run)
        db.commit()
    finally:
        db.close()

    response = c.post(
        "/api/v1/internal/scheduler/sources/retry-degraded",
        headers={"X-Internal-API-Key": "test_internal_key"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["scheduled"] >= 1

    db = SessionLocal()
    try:
        alerts = list(db.scalars(select(Alert).where(Alert.alert_type == "source_health")))
        scheduled_runs = list(db.scalars(select(SourceRun).where(SourceRun.status == "scheduled")))
    finally:
        db.close()
    assert alerts
    assert scheduled_runs


def test_admin_retry_degraded_sources_schedules_retry(monkeypatch) -> None:
    c = client()
    import app.api.v1.admin as admin_api

    monkeypatch.setattr(admin_api, "enqueue_scrape_source", lambda *args, **kwargs: "celery-admin-retry-123")
    db = SessionLocal()
    try:
        source = db.scalar(select(Source).where(Source.key == "grants-gov"))
        assert source is not None
        task_ids = list(
            db.scalars(
                select(Task.id)
                .join(SourceRun, SourceRun.id == Task.source_run_id)
                .where(SourceRun.source_id == source.id)
            )
        )
        if task_ids:
            db.query(Task).filter(Task.id.in_(task_ids)).delete(synchronize_session=False)
        run = SourceRun(source_id=source.id, status="failed", items_found=0, items_created=0, items_updated=0, logs=[])
        db.add(run)
        db.commit()
    finally:
        db.close()

    auth = {"Authorization": f"Bearer {token(c)}"}
    response = c.post("/api/v1/admin/sources/retry-degraded", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    assert payload["scheduled"] >= 1


def test_admin_reseed_default_sources() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    before = c.get("/api/v1/sources", headers=auth)
    assert before.status_code == 200
    before_count = len(before.json())

    response = c.post("/api/v1/admin/sources/reseed-defaults", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 38
    assert payload["after_total"] >= before_count
    assert payload["inserted"] + payload["updated"] >= 1

    sources = c.get("/api/v1/sources", headers=auth)
    assert sources.status_code == 200
    keys = {item["key"] for item in sources.json()}
    assert "novo-nordisk-grants" in keys
    assert "horizon-europe-sedia" in keys
    assert "eic-accelerator" in keys


def test_alert_lifecycle() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    created = c.post(
        "/api/v1/alerts",
        headers=auth,
        json={
            "alert_type": "closing_soon",
            "channel": "email",
            "recipient": "equipo@example.com",
            "subject": "Cierre proximo",
            "message": "Revisar convocatoria antes del cierre.",
        },
    )
    assert created.status_code == 200
    alert_id = created.json()["id"]
    assert created.json()["status"] == "pending"

    paused = c.patch(f"/api/v1/alerts/{alert_id}", headers=auth, json={"status": "paused"})
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    assert paused.json()["sent_at"] is None

    sent = c.patch(f"/api/v1/alerts/{alert_id}", headers=auth, json={"status": "sent"})
    assert sent.status_code == 200
    assert sent.json()["status"] == "sent"
    assert sent.json()["sent_at"] is not None


def test_send_pending_alert_uses_email_delivery_flow() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    created = c.post(
        "/api/v1/alerts",
        headers=auth,
        json={
            "alert_type": "new_opportunity",
            "channel": "email",
            "recipient": "equipo@example.com",
            "subject": "Nueva convocatoria detectada",
            "message": "Hay una oportunidad nueva para revisar.",
        },
    )
    assert created.status_code == 200
    alert_id = created.json()["id"]

    sent = c.post(f"/api/v1/alerts/{alert_id}/send", headers=auth)
    assert sent.status_code == 200
    assert sent.json()["status"] == "sent"
    assert sent.json()["sent_at"] is not None

    logs = c.get("/api/v1/admin/audit-logs", headers=auth)
    assert logs.status_code == 200
    assert any(item["action"] == "send_alert" and item["resource_id"] == alert_id for item in logs.json())


def test_internal_scheduler_sends_due_alerts() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    created = c.post(
        "/api/v1/alerts",
        headers=auth,
        json={
            "alert_type": "closing_soon",
            "channel": "email",
            "recipient": "equipo@example.com",
            "subject": "Alerta programada",
            "message": "Cierre pronto.",
            "scheduled_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
        },
    )
    assert created.status_code == 200
    alert_id = created.json()["id"]

    sent = c.post(
        "/api/v1/internal/scheduler/alerts/send-due",
        headers={"X-Internal-API-Key": "test_internal_key"},
    )
    assert sent.status_code == 200
    assert sent.json()["sent"] >= 1

    updated = c.get("/api/v1/alerts", headers=auth)
    assert updated.status_code == 200
    assert any(item["id"] == alert_id and item["status"] == "sent" for item in updated.json())


def test_generate_recommended_alerts_for_closing_soon() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    create_fixture_opportunity(close_days=3)

    generated = c.post("/api/v1/alerts/generate", headers=auth)
    assert generated.status_code == 200
    payload = generated.json()
    assert any(item["alert_type"] == "closing_soon" for item in payload)

    generated_again = c.post("/api/v1/alerts/generate", headers=auth)
    assert generated_again.status_code == 200
    assert generated_again.json() == []


def test_test_alert_uses_json_payload() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    response = c.post("/api/v1/alerts/test", headers=auth, json={"recipient": "qa@example.com"})
    assert response.status_code == 200
    assert response.json()["status"] == "sent"
    assert response.json()["recipient"] == "qa@example.com"


def test_admin_audit_logs() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    c.post("/api/v1/alerts/test", headers=auth, json={"recipient": "audit@example.com"})
    response = c.get("/api/v1/admin/audit-logs", headers=auth)
    assert response.status_code == 200
    actions = {item["action"] for item in response.json()}
    assert "test_alert" in actions


def test_admin_metrics() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    c.post("/api/v1/sources/" + c.get("/api/v1/sources", headers=auth).json()[0]["id"] + "/run", headers=auth)
    response = c.get("/api/v1/admin/metrics", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    assert payload["active_sources"] >= 1
    assert payload["opportunities"] >= 1
    assert payload["audit_events"] >= 1
    assert "stale_sources" in payload


def test_admin_source_runs_overview() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    response = c.get("/api/v1/admin/source-runs", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    if payload:
        first = payload[0]
        assert "source_name" in first
        assert "source_key" in first
        assert "status" in first


def test_admin_rebuild_embeddings() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    opportunity_id = create_fixture_opportunity()
    response = c.post("/api/v1/admin/embeddings/rebuild?limit=10", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    assert payload["processed"] >= 1
    assert payload["created"] >= 0
    assert payload["updated"] >= 0

    db = SessionLocal()
    try:
        embedding = db.scalar(select(OpportunityEmbedding).where(OpportunityEmbedding.opportunity_id == opportunity_id))
    finally:
        db.close()
    assert embedding is not None
    assert embedding.model_version == EMBEDDING_MODEL_VERSION


def test_source_run_marks_degraded_when_no_candidates(monkeypatch) -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    from app import services as app_services

    class EmptyConnector:
        source_key = "grants-gov"

        async def fetch(self):
            return type(
                "Raw",
                (),
                {
                    "source_key": "grants-gov",
                    "url": "https://www.grants.gov/search-results-detail/empty",
                    "content": "<html></html>",
                    "content_type": "text/html",
                },
            )()

        async def parse(self, raw):
            return []

        async def validate(self, candidate):
            from worker.connectors.base import ValidationResult

            return ValidationResult(ok=True)

    monkeypatch.setattr(app_services, "connector_for", lambda *_args, **_kwargs: EmptyConnector())
    sources = c.get("/api/v1/sources", headers=auth)
    source_id = [item for item in sources.json() if item["key"] == "grants-gov"][0]["id"]
    run = c.post(f"/api/v1/sources/{source_id}/run", headers=auth)
    assert run.status_code == 200
    payload = run.json()
    assert payload["status"] == "degraded"
    assert payload["items_found"] == 0
    diag = next(log for log in payload["logs"] if log.get("message") == "Connector diagnostics")
    assert diag["candidates_parsed"] == 0


def test_internal_connector_probe_requires_key() -> None:
    c = client()
    response = c.post(
        "/api/v1/internal/connectors/probe",
        headers={"X-Internal-API-Key": "wrong"},
        json={"source_key": "grants-gov-rss"},
    )
    assert response.status_code == 401


def test_internal_connector_probe_returns_diagnostics(monkeypatch) -> None:
    c = client()
    import app.api.v1.internal as internal_api

    class StubConnector:
        source_key = "grants-gov-rss"

        async def fetch(self):
            return type(
                "Raw",
                (),
                {
                    "source_key": "grants-gov-rss",
                    "url": "https://example.com/feed.xml",
                    "content": "<rss><channel><item><title>Call</title></item></channel></rss>",
                    "content_type": "application/rss+xml",
                },
            )()

        async def parse(self, raw):
            from worker.connectors.base import OpportunityCandidate

            return [
                OpportunityCandidate(
                    title="Research Call",
                    entity="Example",
                    country="United States",
                    official_url="https://example.com/call",
                    confidence_score=0.9,
                )
            ]

        async def validate(self, candidate):
            from worker.connectors.base import ValidationResult

            return ValidationResult(ok=True)

    monkeypatch.setattr(internal_api, "connector_for", lambda *_args, **_kwargs: StubConnector())
    response = c.post(
        "/api/v1/internal/connectors/probe",
        headers={"X-Internal-API-Key": "test_internal_key"},
        json={"source_key": "grants-gov-rss"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["raw_content_length"] > 0
    assert payload["candidates_parsed"] == 1
    assert payload["candidates_valid"] == 1
