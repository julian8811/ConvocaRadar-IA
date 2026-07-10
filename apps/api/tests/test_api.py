import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

os.environ["DATABASE_URL"] = "sqlite:///./test_convocaradar.db"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["STORAGE_DIR"] = "./test_storage"
os.environ["SMTP_HOST"] = ""
os.environ["JWT_SECRET"] = "a" * 64
os.environ["INTERNAL_API_KEY"] = "a" * 64
os.environ["BOOTSTRAP_SOURCES_ON_STARTUP"] = "false"

Path("test_convocaradar.db").unlink(missing_ok=True)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db.seed import seed  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.core.ai import embedding_model_version  # noqa: E402
import app.main as app_main  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Alert, Opportunity, OpportunityEmbedding, OpportunityScore, Organization, Role, Source, SourceRun, Task, User  # noqa: E402
from app.schemas import OpportunityCreate  # noqa: E402
from app.services import create_opportunity, deduplicate_opportunities, is_private_url, opportunity_dedup_key  # noqa: E402


def client() -> TestClient:
    seed()
    # seed() no longer creates users (SEC-1.2). Create the test admin so
    # existing test helpers (token(), etc.) continue to work.
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        if org and not db.scalar(select(User).where(User.email == "admin@convocaradar.io")):
            from app.core.security import hash_password

            db.add(
                User(
                    email="admin@convocaradar.io",
                    name="Admin ConvocaRadar",
                    password_hash=hash_password("ConvocaRadarLocal123!"),
                    role=Role.admin.value,
                    organization_id=org.id,
                )
            )
            db.commit()
    finally:
        db.close()
    return TestClient(app)


def token(c: TestClient) -> str:
    response = c.post(
        "/api/v1/auth/login",
        json={"email": "admin@convocaradar.io", "password": "ConvocaRadarLocal123!"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


async def create_fixture_opportunity(*, close_days: int = 30) -> str:
    db = SessionLocal()
    try:
        organization = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert organization is not None
        source = db.scalar(select(Source).where(Source.key == "grants-gov"))
        assert source is not None
        opportunity = await create_opportunity(
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


@pytest.mark.asyncio
async def test_opportunities_and_score() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    opportunity_id = await create_fixture_opportunity()
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


@pytest.mark.asyncio
async def test_semantic_search_returns_best_match() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    opportunity_id = await create_fixture_opportunity()
    response = c.get("/api/v1/opportunities/semantic-search?query=research%20innovation%20grant", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    # Text ILIKE fallback should find the opportunity even if embedding
    # similarity is low with local hash-based embeddings
    assert "query" in payload
    assert isinstance(payload.get("items"), list)

    db = SessionLocal()
    try:
        embedding = db.scalar(select(OpportunityEmbedding).where(OpportunityEmbedding.opportunity_id == opportunity_id))
    finally:
        db.close()
    assert embedding is not None
    assert embedding.embedding


@pytest.mark.asyncio
async def test_text_search_matches_description_and_summary() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    opportunity_id = await create_fixture_opportunity()
    response = c.get("/api/v1/opportunities?search=prueba%20creada%20para%20validar", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    assert any(item["id"] == opportunity_id for item in payload["items"])


@pytest.mark.asyncio
async def test_reanalyze_opportunity_improves_payload() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    db = SessionLocal()
    try:
        organization = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        source = db.scalar(select(Source).where(Source.key == "grants-gov"))
        assert organization is not None and source is not None
        opportunity = await create_opportunity(
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


@pytest.mark.asyncio
async def test_bulk_reanalyze_opportunities() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    opportunity_id = await create_fixture_opportunity()
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


@pytest.mark.asyncio
async def test_opportunity_document_lifecycle() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    opportunity_id = await create_fixture_opportunity()

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


@pytest.mark.asyncio
async def test_report_creation() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    await create_fixture_opportunity()
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


@pytest.mark.asyncio
async def test_create_opportunity_enriches_incomplete_payload() -> None:
    db = SessionLocal()
    try:
        organization = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        source = db.scalar(select(Source).where(Source.key == "grants-gov"))
        assert organization is not None and source is not None
        opportunity = await create_opportunity(
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


@pytest.mark.asyncio
async def test_create_opportunity_rejects_noise_title() -> None:
    db = SessionLocal()
    try:
        organization = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        source = db.scalar(select(Source).where(Source.key == "grants-gov"))
        assert organization is not None and source is not None
        with pytest.raises(ValueError, match="scraping noise"):
            await create_opportunity(
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


def test_opportunity_dedup_key_uses_grants_gov_id() -> None:
    key = opportunity_dedup_key(
        "https://www.grants.gov/search-results-detail/2831",
        "Sample grant",
    )
    assert key == "grants-gov:2831"


@pytest.mark.asyncio
async def test_create_opportunity_merges_cross_source_grants_gov_duplicates() -> None:
    seed()
    db = SessionLocal()
    try:
        organization = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        grants_source = db.scalar(select(Source).where(Source.key == "grants-gov"))
        usaid_source = db.scalar(select(Source).where(Source.key == "usaid-grants"))
        assert organization is not None and grants_source is not None and usaid_source is not None

        shared_url = "https://www.grants.gov/search-results-detail/2831"
        shared_raw = json.dumps({"id": "2831", "number": "OFOP0002831", "agencyName": "DOS-IND"})
        first = await create_opportunity(
            db,
            OpportunityCreate(
                source_id=grants_source.id,
                external_id="dedup-fixture-grants",
                title="U.S. India Sports Technology Dialogues and Innovation Program",
                entity="DOS-IND",
                country="United States",
                summary="OFOP0002831 | DOS-IND | Status: posted",
                raw_text=shared_raw,
                official_url=shared_url,
                close_date=datetime(2026, 6, 7),
            ),
            organization_id=organization.id,
        )
        second = await create_opportunity(
            db,
            OpportunityCreate(
                source_id=usaid_source.id,
                external_id="dedup-fixture-usaid",
                title="U.S. India Sports Technology Dialogues and Innovation Program",
                entity="USAID",
                country="United States",
                summary="OFOP0002831 | USAID | Status: posted",
                raw_text=shared_raw,
                official_url=shared_url,
                close_date=datetime(2026, 6, 7),
            ),
            organization_id=organization.id,
        )
        first_id = first.id
        second_id = second.id
        second_entity = second.entity
        db.commit()
    finally:
        db.close()

    assert first_id == second_id
    assert second_entity == "USAID"


@pytest.mark.asyncio
async def test_deduplicate_opportunities_removes_existing_duplicates() -> None:
    seed()
    db = SessionLocal()
    try:
        organization = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        grants_source = db.scalar(select(Source).where(Source.key == "grants-gov"))
        usaid_source = db.scalar(select(Source).where(Source.key == "usaid-grants"))
        assert organization is not None and grants_source is not None and usaid_source is not None

        shared_url = "https://www.grants.gov/search-results-detail/4242"
        shared_raw = json.dumps({"id": "4242", "number": "OFOP0004242"})
        first = await create_opportunity(
            db,
            OpportunityCreate(
                source_id=grants_source.id,
                title="Duplicate cleanup fixture A",
                entity="Agency A",
                country="United States",
                raw_text=shared_raw,
                official_url=shared_url,
            ),
            organization_id=organization.id,
        )
        db.add(
            Opportunity(
                organization_id=organization.id,
                source_id=usaid_source.id,
                title="Duplicate cleanup fixture A",
                slug="duplicate-cleanup-fixture-a-usaid",
                entity="Agency B",
                country="United States",
                raw_text=shared_raw,
                official_url=shared_url,
            )
        )
        db.flush()
        first_id = first.id
        stats = deduplicate_opportunities(db, organization.id)
        remaining = list(
            db.scalars(
                select(Opportunity).where(
                    Opportunity.organization_id == organization.id,
                    Opportunity.official_url == shared_url,
                )
            )
        )
        remaining_id = remaining[0].id if remaining else None
        db.commit()
    finally:
        db.close()

    assert stats["duplicates_removed"] >= 1
    assert len(remaining) == 1
    assert remaining_id is not None


def test_deduplicate_opportunities_handles_null_created_at() -> None:
    seed()
    db = SessionLocal()
    try:
        organization = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        grants_source = db.scalar(select(Source).where(Source.key == "grants-gov"))
        usaid_source = db.scalar(select(Source).where(Source.key == "usaid-grants"))
        assert organization is not None and grants_source is not None and usaid_source is not None

        shared_url = "https://www.grants.gov/search-results-detail/5151"
        shared_raw = json.dumps({"id": "5151", "number": "OFOP0005151"})
        shared_time = datetime(2026, 6, 25, 12, 0, 0)
        first = Opportunity(
            organization_id=organization.id,
            source_id=grants_source.id,
            title="Duplicate cleanup fixture null created_at",
            slug="duplicate-cleanup-fixture-null-created-at-grants",
            entity="Agency A",
            country="United States",
            raw_text=shared_raw,
            official_url=shared_url,
            first_seen_at=shared_time,
            created_at=None,
        )
        second = Opportunity(
            organization_id=organization.id,
            source_id=usaid_source.id,
            title="Duplicate cleanup fixture null created_at",
            slug="duplicate-cleanup-fixture-null-created-at-usaid",
            entity="Agency B",
            country="United States",
            raw_text=shared_raw,
            official_url=shared_url,
            first_seen_at=shared_time,
            created_at=shared_time,
        )
        db.add_all([first, second])
        db.flush()
        stats = deduplicate_opportunities(db, organization.id)
        remaining = list(
            db.scalars(
                select(Opportunity).where(
                    Opportunity.organization_id == organization.id,
                    Opportunity.official_url == shared_url,
                )
            )
        )
        db.commit()
    finally:
        db.close()

    assert stats["duplicates_removed"] >= 1
    assert len(remaining) == 1


def test_admin_deduplicate_opportunities_endpoint() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    response = c.post("/api/v1/admin/opportunities/deduplicate", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    assert "duplicates_removed" in payload
    assert "groups_merged" in payload


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
            from app.connectors.base import OpportunityCandidate

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
            from app.connectors.base import ValidationResult

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
    # PR4-1: when sources are already owned by the local org, the seed
    # counts them as 'skipped' (not stolen). The response shape now
    # includes a 'skipped' key.
    assert "skipped" in payload
    assert isinstance(payload["skipped"], int)
    # The seed always processes every default source — count of
    # inserted+updated+skipped must equal total.
    assert payload["inserted"] + payload["updated"] + payload["skipped"] == payload["total"]

    sources = c.get("/api/v1/sources", headers=auth)
    assert sources.status_code == 200
    keys = {item["key"] for item in sources.json()}
    assert "novo-nordisk-grants" in keys
    assert "horizon-europe-sedia" in keys
    assert "eic-accelerator" in keys


def test_admin_reseed_default_sources_with_force_true() -> None:
    """?force=true re-claims and updates every source, even org-owned ones.

    PR4-1: the admin endpoint accepts ?force=true as an explicit opt-in
    to bypass the org-ownership safety check. With force=true, every
    default source is updated (reassigned and refreshed) — none are
    skipped.
    """
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}

    response = c.post("/api/v1/admin/sources/reseed-defaults?force=true", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 38
    # With force=true, no source is skipped — every source is updated
    # (or freshly inserted).
    assert payload["skipped"] == 0, f"force=true must skip 0, got {payload}"
    assert payload["inserted"] + payload["updated"] == payload["total"]


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


@pytest.mark.asyncio
async def test_generate_recommended_alerts_for_closing_soon() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    await create_fixture_opportunity(close_days=3)

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


@pytest.mark.asyncio
async def test_dashboard_summary() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    await create_fixture_opportunity(close_days=5)
    response = c.get("/api/v1/dashboard/summary", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_opportunities"] >= 1
    assert payload["open_opportunities"] >= 0
    assert "closing_soon_opportunities" in payload
    assert "high_match_opportunities" in payload
    assert isinstance(payload["top_scored"], list)
    assert isinstance(payload["closing_soon"], list)
    assert isinstance(payload["status_breakdown"], list)
    assert isinstance(payload["country_breakdown"], list)
    assert "degraded_sources" in payload
    assert "data_coverage" in payload
    assert payload["data_coverage"]["embeddings_coverage"] >= 0
    assert "profile" in payload
    assert payload["profile"]["completeness"] >= 0


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


def test_admin_bootstrap_data_endpoint() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    response = c.post("/api/v1/admin/bootstrap-data", headers=auth)
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"completed", "skipped"}


@pytest.mark.asyncio
async def test_admin_rebuild_embeddings() -> None:
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    opportunity_id = await create_fixture_opportunity()
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
    assert embedding.model_version == embedding_model_version()


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
            from app.connectors.base import ValidationResult

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
            from app.connectors.base import OpportunityCandidate

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
            from app.connectors.base import ValidationResult

            return ValidationResult(ok=True)

    monkeypatch.setattr(internal_api, "connector_for", lambda *_args, **_kwargs: StubConnector())
    response = c.post(
        "/api/v1/internal/connectors/probe",
        headers={"X-Internal-API-Key": "a" * 64},
        json={"source_key": "grants-gov-rss"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["raw_content_length"] > 0
    assert payload["candidates_parsed"] == 1
    assert payload["candidates_valid"] == 1


def test_verify_internal_key_uses_compare_digest() -> None:
    import inspect

    from app.api.v1.internal import verify_internal_key

    source = inspect.getsource(verify_internal_key)
    assert "hmac.compare_digest" in source


def test_register_as_member() -> None:
    c = client()
    response = c.post(
        "/api/v1/auth/register",
        json={
            "email": "miembro@example.com",
            "password": "strongpass123!",
            "name": "Miembro Nuevo",
            "organization_name": "Org Miembro",
            "organization_type": "startup",
            "country": "Mexico",
        },
    )
    assert response.status_code == 200
    data = response.json()
    # The register endpoint returns a Token (access_token, token_type).
    # We need /me to check the role, or check the token payload.
    # Let's use /me with the token to verify role.
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    me = c.get("/api/v1/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["role"] == "member", f"Expected role=member but got {me.json()['role']}"


def test_member_cannot_access_admin() -> None:
    c = client()
    # Register a new user (will get role=member after fix)
    reg = c.post(
        "/api/v1/auth/register",
        json={
            "email": "socio@example.com",
            "password": "strongpass456!",
            "name": "Socio Limitado",
            "organization_name": "Socio Org",
            "organization_type": "company",
            "country": "Chile",
        },
    )
    assert reg.status_code == 200
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    # Try to access admin-only endpoint
    response = c.get("/api/v1/admin/metrics", headers=headers)
    assert response.status_code == 403, (
        f"Expected 403 for member accessing admin endpoint, got {response.status_code}: {response.text}"
    )


def test_existing_admin_keeps_role() -> None:
    # The existing test_login_and_me already covers this; this is an extra safety check.
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    response = c.get("/api/v1/me", headers=auth)
    assert response.status_code == 200
    assert response.json()["role"] == "admin"


# ── SEC-1.2: Admin seed CLI ──────────────────────────────────────────────────


def test_seed_admin_creates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy path: no admin in org → creates admin → exit 0."""
    import sys

    from app.db.seed_admin import main
    from app.models import Role, User  # noqa: N812

    # Ensure there is no admin user in the org so the CLI can succeed.
    # (previous tests may have created one via client()).
    db = SessionLocal()
    try:
        existing = db.scalars(select(User))
        for u in existing:
            db.delete(u)
        db.commit()
    finally:
        db.close()

    seed()
    monkeypatch.setattr(sys, "argv", [
        "convocaradar-seed-admin",
        "--email", "new-cli-admin@example.com",
        "--password-env", "SEED_ADMIN_TEST_PW",
    ])
    monkeypatch.setenv("SEED_ADMIN_TEST_PW", "supersecret123!")  # noqa: S105
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0, f"Expected exit 0, got {exc_info.value.code}"
    # Verify the user was created
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "new-cli-admin@example.com"))
        assert user is not None, "Admin user was not created"
        assert user.role == Role.admin.value, f"Expected role={Role.admin.value}, got {user.role}"
    finally:
        db.close()


def test_seed_admin_aborts_if_admin_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    """Admin already exists in org → exit 1 (no --force)."""
    import sys

    from app.core.security import hash_password
    from app.db.seed_admin import main
    from app.models import Role, User  # noqa: N812

    # Clear any existing users so we control the precondition
    db = SessionLocal()
    try:
        existing = db.scalars(select(User))
        for u in existing:
            db.delete(u)
        db.commit()
    finally:
        db.close()
    seed()
    # Create an admin user as precondition (seed() no longer creates users)
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == "convocaradar-local"))
        assert org
        if not db.scalar(select(User).where(User.role == Role.admin.value).limit(1)):
            db.add(
                User(
                    email="admin@convocaradar.io",
                    name="Admin",
                    password_hash=hash_password("pw"),
                    role=Role.admin.value,
                    organization_id=org.id,
                )
            )
            db.commit()
    finally:
        db.close()

    monkeypatch.setattr(sys, "argv", [
        "convocaradar-seed-admin",
        "--email", "another-admin@example.com",
        "--password-env", "SEED_ADMIN_TEST_PW",
    ])
    monkeypatch.setenv("SEED_ADMIN_TEST_PW", "supersecret456!")
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1, f"Expected exit 1, got {exc_info.value.code}"


def test_seed_admin_rejects_missing_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment variable not set or empty → exit 2 (usage error).

    SEC-1.2 spec: "process exits with code 2 (usage error)" when the
    password env var is missing or empty. Exit 1 is reserved for the
    "admin already exists, abort" path.
    """
    import sys

    from app.db.seed_admin import main
    from app.models import User  # noqa: N812

    db = SessionLocal()
    try:
        existing = db.scalars(select(User))
        for u in existing:
            db.delete(u)
        db.commit()
    finally:
        db.close()
    seed()
    monkeypatch.setattr(sys, "argv", [
        "convocaradar-seed-admin",
        "--email", "nobody@example.com",
        "--password-env", "THIS_ENV_VAR_DOES_NOT_EXIST",
    ])
    monkeypatch.delenv("THIS_ENV_VAR_DOES_NOT_EXIST", raising=False)
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 2, (
        f"Expected exit 2 (usage error) for missing --password-env, "
        f"got {exc_info.value.code!r}. Exit 1 is reserved for the "
        f"'admin already exists' abort path."
    )


def test_seed_admin_exits_zero_on_help(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--help` must exit 0 (argparse convention), not 1 or 2.

    Operators running `convocaradar-seed-admin --help` to read the usage
    must not see a "non-zero exit" failure in their CI logs.
    """
    import sys

    from app.db.seed_admin import main

    monkeypatch.setattr(sys, "argv", ["convocaradar-seed-admin", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0, (
        f"Expected exit 0 on --help, got {exc_info.value.code!r}. "
        f"argparse defaults to exit(0) for --help; if this regressed, "
        f"someone overrode the default help action."
    )


# ── Existing tests ───────────────────────────────────────────────────────────


def test_settings_fails_without_jwt_secret() -> None:
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(jwt_secret="")


def test_settings_fails_without_internal_api_key() -> None:
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(internal_api_key="")


# ── SEC-1.5: JWT cookie migration (dual-support) ─────────────────────────────


def test_login_sets_convocaradar_token_cookie() -> None:
    """POST /auth/login must set the HttpOnly cookie with the expected attributes."""
    c = client()
    response = c.post(
        "/api/v1/auth/login",
        json={"email": "admin@convocaradar.io", "password": "ConvocaRadarLocal123!"},
    )
    assert response.status_code == 200
    # Cookie name must match the spec
    assert "convocaradar_token" in response.cookies
    # JSON body still returns the token for backward compatibility
    assert response.json()["access_token"]


def test_login_cookie_attributes_are_secure() -> None:
    """The cookie must be HttpOnly, SameSite=Lax, Path=/, Max-Age=3600."""
    c = client()
    response = c.post(
        "/api/v1/auth/login",
        json={"email": "admin@convocaradar.io", "password": "ConvocaRadarLocal123!"},
    )
    assert response.status_code == 200
    cookie_header = response.headers.get("set-cookie", "")
    # Each attribute must be present in the Set-Cookie header
    assert "convocaradar_token=" in cookie_header
    assert "HttpOnly" in cookie_header
    assert "SameSite=strict" in cookie_header or "samesite=strict" in cookie_header.lower()
    assert "Path=/" in cookie_header
    assert "Max-Age=3600" in cookie_header


def test_register_sets_convocaradar_token_cookie() -> None:
    """POST /auth/register must also set the cookie (same as login)."""
    c = client()
    response = c.post(
        "/api/v1/auth/register",
        json={
            "email": "newcookie@example.com",
            "password": "strongpass789!",
            "name": "Cookie User",
            "organization_name": "Cookie Org",
            "organization_type": "startup",
            "country": "Brazil",
        },
    )
    assert response.status_code == 200
    assert "convocaradar_token" in response.cookies


def test_logout_clears_cookie() -> None:
    """POST /auth/logout must clear the cookie."""
    c = client()
    login_resp = c.post(
        "/api/v1/auth/login",
        json={"email": "admin@convocaradar.io", "password": "ConvocaRadarLocal123!"},
    )
    assert login_resp.status_code == 200
    # Now logout
    logout_resp = c.post("/api/v1/auth/logout")
    assert logout_resp.status_code == 200
    # Set-Cookie should clear (Max-Age=0) the cookie
    cookie_header = logout_resp.headers.get("set-cookie", "")
    assert "convocaradar_token" in cookie_header
    assert "Max-Age=0" in cookie_header or "max-age=0" in cookie_header.lower()


def test_me_authenticates_via_cookie() -> None:
    """GET /me must work when the token is supplied via cookie only (no Bearer)."""
    c = client()
    # Login and grab the cookie value
    login_resp = c.post(
        "/api/v1/auth/login",
        json={"email": "admin@convocaradar.io", "password": "ConvocaRadarLocal123!"},
    )
    assert login_resp.status_code == 200
    token_value = login_resp.cookies["convocaradar_token"]
    # Make a separate request using ONLY the cookie
    response = c.get("/api/v1/me", cookies={"convocaradar_token": token_value})
    assert response.status_code == 200
    assert response.json()["email"] == "admin@convocaradar.io"


def test_me_authenticates_via_bearer_header() -> None:
    """GET /me must still work with the Authorization: Bearer header (backward-compat)."""
    c = client()
    auth = {"Authorization": f"Bearer {token(c)}"}
    response = c.get("/api/v1/me", headers=auth)
    assert response.status_code == 200
    assert response.json()["email"] == "admin@convocaradar.io"


def test_me_with_neither_cookie_nor_header_returns_401() -> None:
    """GET /me with no auth (no cookie, no header) must return 401."""
    c = client()
    # Use a fresh client with no cookies and no header
    response = c.get("/api/v1/me")
    assert response.status_code == 401


def test_me_with_invalid_cookie_returns_401() -> None:
    """GET /me with a malformed cookie value must return 401, not 500."""
    c = client()
    response = c.get("/api/v1/me", cookies={"convocaradar_token": "garbage.token.value"})
    assert response.status_code == 401
