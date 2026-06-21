from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import ipaddress
import re
from datetime import UTC, datetime, timedelta
from html import escape
from functools import lru_cache
from urllib.parse import urlparse

import httpx
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.config import get_settings
from app.core.ai import (
    EMBEDDING_MODEL_VERSION,
    build_embedding,
    build_local_extraction,
    compose_embedding_text,
    cosine_similarity,
    extract_opportunity_structured,
    infer_language,
    summarize_opportunity_text,
)
from app.models import (
    Alert,
    AuditLog,
    PGVECTOR_AVAILABLE,
    Opportunity,
    OpportunityDocument,
    OpportunityEmbedding,
    OpportunityScore,
    OpportunityStatus,
    Organization,
    OrganizationProfile,
    Priority,
    Report,
    Source,
    SourceRun,
    Task,
    User,
)
from app.schemas import OpportunityCreate


def connector_for(source_key: str, base_url: str | None = None, source_type: str | None = None):
    from worker.connectors.factory import connector_for as worker_connector_for

    return worker_connector_for(source_key, base_url, source_type)


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return value or "item"


def audit(db: Session, action: str, resource_type: str, user: User | None, resource_id: str | None = None) -> None:
    db.add(
        AuditLog(
            organization_id=user.organization_id if user else None,
            user_id=user.id if user else None,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
        )
    )


def _source_health_status(recent_runs: list[SourceRun]) -> str:
    failures = sum(1 for run in recent_runs if run.status == "failed")
    if not recent_runs:
        return "idle"
    if recent_runs[0].status == "failed" or failures >= 3:
        return "failing"
    if failures > 0:
        return "degraded"
    return "healthy"


def create_source_health_alert(db: Session, source: Source, *, reason: str, recipient_email: str | None = None) -> Alert | None:
    if not source.organization_id:
        return None
    recipient = recipient_email
    if not recipient:
        recipient = db.scalar(
            select(User.email)
            .where(User.organization_id == source.organization_id, User.role == "admin")
            .order_by(User.created_at.asc())
        )
    if not recipient:
        return None
    subject = f"Fuente en observacion: {source.name}"
    existing = db.scalar(
        select(Alert).where(
            Alert.organization_id == source.organization_id,
            Alert.alert_type == "source_health",
            Alert.recipient == recipient,
            Alert.subject == subject,
            Alert.status.in_(["pending", "sent", "paused"]),
        )
    )
    if existing:
        return None
    alert = Alert(
        organization_id=source.organization_id,
        opportunity_id=None,
        alert_type="source_health",
        channel="email",
        recipient=recipient,
        subject=subject,
        message=(
            f"La fuente '{source.name}' ({source.key}) muestra problemas: {reason}. "
            "Revisar selector, credenciales, endpoint o disponibilidad."
        ),
        status="pending",
    )
    db.add(alert)
    return alert


def _parse_ai_close_date(value: object) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def enrich_opportunity_payload(data: OpportunityCreate) -> OpportunityCreate:
    raw_text = data.raw_text.strip()
    if not raw_text or len(raw_text) < 120:
        merged = data.model_dump()
        if merged.get("language") in {None, "", "auto"}:
            merged["language"] = infer_language(" ".join([data.title, data.summary, data.raw_text, data.description]), fallback="es")
        return OpportunityCreate(**merged)
    if data.summary and data.categories and data.requirements and data.confidence_score >= 0.75:
        merged = data.model_dump()
        if merged.get("language") in {None, "", "auto"}:
            merged["language"] = infer_language(" ".join([data.title, data.summary, data.raw_text, data.description]), fallback="es")
        return OpportunityCreate(**merged)
    extraction = create_ai_extraction(raw_text)
    merged = data.model_dump()
    merged["title"] = data.title or str(extraction.get("title") or merged["title"])
    merged["entity"] = data.entity or str(extraction.get("entity") or merged["entity"])
    merged["country"] = (
        data.country if data.country and data.country != "Por validar" else str(extraction.get("country") or merged["country"])
    )
    merged["categories"] = data.categories or list(extraction.get("category") or [])
    merged["topics"] = data.topics or list(extraction.get("matched_keywords") or [])
    merged["summary"] = data.summary or str(extraction.get("summary") or merged["summary"])
    merged["description"] = data.description or str(extraction.get("summary") or merged["description"])
    merged["requirements"] = data.requirements or list(extraction.get("requirements") or [])
    merged["documents_required"] = data.documents_required or list(extraction.get("documents_required") or [])
    merged["evaluation_criteria"] = data.evaluation_criteria or list(extraction.get("evaluation_criteria") or [])
    merged["restrictions"] = data.restrictions or list(extraction.get("restrictions") or [])
    merged["risk_flags"] = data.risk_flags or list(extraction.get("risks") or [])
    merged["funding_amount_raw"] = data.funding_amount_raw or extraction.get("funding_amount_raw")
    merged["language"] = data.language if data.language not in {"", "auto"} else str(extraction.get("language") or infer_language(raw_text, fallback="es"))
    merged["confidence_score"] = round(
        max(float(data.confidence_score), float(extraction.get("confidence") or data.confidence_score)),
        2,
    )
    merged["close_date"] = data.close_date or _parse_ai_close_date(extraction.get("close_date"))
    return OpportunityCreate(**merged)


def opportunity_embedding_text(opportunity: Opportunity) -> str:
    parts = [
        opportunity.title,
        opportunity.entity,
        opportunity.country,
        opportunity.region or "",
        opportunity.summary or opportunity.description,
        opportunity.raw_text,
        opportunity.official_url or "",
        opportunity.application_url or "",
        opportunity.funding_amount_raw or "",
    ]
    if opportunity.categories:
        parts.append("Categories: " + ", ".join(opportunity.categories))
    if opportunity.topics:
        parts.append("Topics: " + ", ".join(opportunity.topics))
    if opportunity.requirements:
        parts.append("Requirements: " + ", ".join(opportunity.requirements))
    if opportunity.documents_required:
        parts.append("Documents: " + ", ".join(opportunity.documents_required))
    if opportunity.evaluation_criteria:
        parts.append("Criteria: " + ", ".join(opportunity.evaluation_criteria))
    if opportunity.restrictions:
        parts.append("Restrictions: " + ", ".join(opportunity.restrictions))
    if opportunity.risk_flags:
        parts.append("Risks: " + ", ".join(opportunity.risk_flags))
    return compose_embedding_text(parts[0], "\n".join(part for part in parts[1:3] if part), "\n".join(part for part in parts[3:] if part))


def opportunity_reanalysis_text(db: Session, opportunity: Opportunity) -> str:
    parts = [
        opportunity.title,
        opportunity.entity,
        opportunity.country,
        opportunity.summary,
        opportunity.raw_text,
        opportunity.official_url or "",
        opportunity.application_url or "",
    ]
    documents = list(
        db.scalars(
            select(OpportunityDocument)
            .where(OpportunityDocument.opportunity_id == opportunity.id)
            .order_by(OpportunityDocument.created_at.desc())
            .limit(5)
        )
    )
    for document in documents:
        if document.text_content:
            parts.append(document.text_content)
    if opportunity.categories:
        parts.append("Categories: " + ", ".join(opportunity.categories))
    if opportunity.topics:
        parts.append("Topics: " + ", ".join(opportunity.topics))
    if opportunity.requirements:
        parts.append("Requirements: " + ", ".join(opportunity.requirements))
    if opportunity.documents_required:
        parts.append("Documents: " + ", ".join(opportunity.documents_required))
    return compose_embedding_text(parts[0], "\n".join(part for part in parts[1:3] if part), "\n".join(part for part in parts[3:] if part))


def upsert_opportunity_embedding(db: Session, opportunity: Opportunity) -> OpportunityEmbedding:
    source_text = opportunity_embedding_text(opportunity)
    vector = build_embedding(source_text)
    existing = db.scalar(select(OpportunityEmbedding).where(OpportunityEmbedding.opportunity_id == opportunity.id))
    if existing:
        existing.organization_id = opportunity.organization_id
        existing.source_text = source_text
        existing.embedding = vector
        existing.model_version = EMBEDDING_MODEL_VERSION
        return existing
    embedding = OpportunityEmbedding(
        opportunity_id=opportunity.id,
        organization_id=opportunity.organization_id,
        source_text=source_text,
        embedding=vector,
        model_version=EMBEDDING_MODEL_VERSION,
    )
    db.add(embedding)
    return embedding


def rebuild_opportunity_embeddings(db: Session, organization_id: str, *, limit: int | None = None) -> dict[str, int]:
    scope = or_(Opportunity.organization_id == organization_id, Opportunity.organization_id.is_(None))
    stmt = select(Opportunity).where(scope).order_by(Opportunity.updated_at.desc())
    if limit is not None:
        stmt = stmt.limit(limit)
    opportunities = list(db.scalars(stmt))
    created = 0
    updated = 0
    for opportunity in opportunities:
        existing = db.scalar(select(OpportunityEmbedding).where(OpportunityEmbedding.opportunity_id == opportunity.id))
        source_text = opportunity_embedding_text(opportunity)
        vector = build_embedding(source_text)
        if existing:
            existing.organization_id = opportunity.organization_id
            existing.source_text = source_text
            existing.embedding = vector
            existing.model_version = EMBEDDING_MODEL_VERSION
            updated += 1
            continue
        db.add(
            OpportunityEmbedding(
                opportunity_id=opportunity.id,
                organization_id=opportunity.organization_id,
                source_text=source_text,
                embedding=vector,
                model_version=EMBEDDING_MODEL_VERSION,
            )
        )
        created += 1
    return {"processed": len(opportunities), "created": created, "updated": updated}


def _supports_vector_search(db: Session) -> bool:
    return PGVECTOR_AVAILABLE and db.bind is not None and db.bind.dialect.name == "postgresql"


def reanalyze_opportunity(db: Session, opportunity: Opportunity, *, force: bool = False) -> Opportunity:
    text = opportunity_reanalysis_text(db, opportunity)
    if not text.strip():
        return opportunity
    extraction = create_ai_extraction(text)
    changed = False
    if force or not opportunity.summary:
        opportunity.summary = str(extraction.get("summary") or opportunity.summary)
        changed = True
    if force or not opportunity.requirements:
        opportunity.requirements = list(extraction.get("requirements") or opportunity.requirements)
        changed = True
    if force or not opportunity.documents_required:
        opportunity.documents_required = list(extraction.get("documents_required") or opportunity.documents_required)
        changed = True
    if force or not opportunity.risk_flags:
        opportunity.risk_flags = list(extraction.get("risks") or opportunity.risk_flags)
        changed = True
    if force or not opportunity.categories:
        opportunity.categories = list(extraction.get("category") or opportunity.categories)
        changed = True
    if force or not opportunity.topics:
        opportunity.topics = list(extraction.get("matched_keywords") or opportunity.topics)
        changed = True
    if force or opportunity.country == "Por validar":
        opportunity.country = str(extraction.get("country") or opportunity.country)
        changed = True
    if force or not opportunity.funding_amount_raw:
        opportunity.funding_amount_raw = extraction.get("funding_amount_raw") or opportunity.funding_amount_raw
        changed = True
    confidence = float(extraction.get("confidence") or opportunity.confidence_score or 0.5)
    if force or confidence > opportunity.confidence_score:
        opportunity.confidence_score = round(confidence, 2)
        changed = True
    close_date = _parse_ai_close_date(extraction.get("close_date"))
    if close_date and (force or not opportunity.close_date):
        opportunity.close_date = close_date
        changed = True
    if changed:
        opportunity.status = inferred_opportunity_status(opportunity.close_date, " ".join([opportunity.summary, opportunity.raw_text]))
        upsert_opportunity_embedding(db, opportunity)
    return opportunity


def semantic_search_opportunities(
    db: Session,
    organization_id: str,
    query: str,
    *,
    limit: int = 10,
) -> list[tuple[Opportunity, float]]:
    query_vector = build_embedding(query)
    query_terms = {token for token in re.findall(r"[a-z0-9]+", query.lower()) if token}
    scope = or_(Opportunity.organization_id == organization_id, Opportunity.organization_id.is_(None))
    if _supports_vector_search(db):
        distance_expr = OpportunityEmbedding.embedding.cosine_distance(query_vector)
        rows = list(
            db.execute(
                select(Opportunity, distance_expr.label("distance"))
                .join(OpportunityEmbedding, OpportunityEmbedding.opportunity_id == Opportunity.id)
                .where(scope)
                .order_by(distance_expr.asc(), Opportunity.created_at.desc())
                .limit(limit * 4)
            )
        )
        results: list[tuple[Opportunity, float]] = []
        for opportunity, distance in rows:
            similarity = round(max(0.0, 1.0 - float(distance or 0.0)), 4)
            lexical = _lexical_search_score(query_terms, opportunity)
            results.append((opportunity, round(min(1.0, (similarity * 0.8) + (lexical * 0.2)), 4)))
        if results:
            results.sort(key=lambda item: item[1], reverse=True)
            return results[:limit]

    opportunities = list(
        db.scalars(
            select(Opportunity)
            .where(scope)
            .order_by(Opportunity.created_at.desc())
            .limit(500)
        )
    )
    scored: list[tuple[Opportunity, float]] = []
    for opportunity in opportunities:
        embedding = db.scalar(select(OpportunityEmbedding).where(OpportunityEmbedding.opportunity_id == opportunity.id))
        if not embedding:
            embedding = upsert_opportunity_embedding(db, opportunity)
            db.flush()
        similarity = cosine_similarity(query_vector, list(embedding.embedding or []))
        lexical = _lexical_search_score(query_terms, opportunity)
        scored.append((opportunity, round(min(1.0, (similarity * 0.7) + (lexical * 0.3)), 4)))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:limit]


def _lexical_search_score(query_terms: set[str], opportunity: Opportunity) -> float:
    if not query_terms:
        return 0.0
    haystack_parts = [
        opportunity.title,
        opportunity.entity,
        opportunity.country,
        opportunity.summary,
        opportunity.description,
        opportunity.raw_text,
        " ".join(opportunity.categories or []),
        " ".join(opportunity.topics or []),
        " ".join(opportunity.requirements or []),
        opportunity.official_url or "",
        opportunity.application_url or "",
    ]
    haystack = " ".join(part for part in haystack_parts if part).lower()
    if not haystack.strip():
        return 0.0
    haystack_terms = set(re.findall(r"[a-z0-9]+", haystack))
    overlap = len(query_terms & haystack_terms)
    coverage = overlap / max(len(query_terms), 1)
    title_boost = 0.15 if any(term in opportunity.title.lower() for term in query_terms) else 0.0
    category_boost = 0.1 if any(term in " ".join(opportunity.categories or []).lower() for term in query_terms) else 0.0
    return round(min(1.0, coverage + title_boost + category_boost), 4)


def opportunity_status(close_date: datetime | None) -> str:
    if not close_date:
        return OpportunityStatus.unknown.value
    now = datetime.now(UTC).replace(tzinfo=None)
    days = get_settings().scraping_closing_soon_days
    if close_date < now:
        return OpportunityStatus.closed.value
    if close_date <= now + timedelta(days=days):
        return OpportunityStatus.closing_soon.value
    return OpportunityStatus.open.value


def inferred_opportunity_status(close_date: datetime | None, text: str = "") -> str:
    status = opportunity_status(close_date)
    if status == OpportunityStatus.unknown.value and re.search(r"\b(open|posted|abierta|abierto)\b", text, re.IGNORECASE):
        return OpportunityStatus.open.value
    return status


def priority_for_score(score: float) -> str:
    if score >= 85:
        return Priority.high.value
    if score >= 65:
        return Priority.medium.value
    if score >= 40:
        return Priority.low.value
    return Priority.not_recommended.value


def is_private_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return True
    host = parsed.hostname
    if not host:
        return True
    host = host.lower()
    if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        return True
    if host.endswith(".local") or host.endswith(".internal") or host.endswith(".lan") or host.endswith(".corp"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast


def validate_source_url(source: Source) -> None:
    if is_private_url(source.base_url):
        raise ValueError("Source URL is not allowed")
    host = urlparse(source.base_url).hostname or ""
    if source.allowed_domains and not any(host == allowed or host.endswith(f".{allowed}") for allowed in source.allowed_domains):
        raise ValueError("Source URL host is outside the allowed domains")


def is_public_http_url(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and not is_private_url(url)


def is_noise_title(title: str | None) -> bool:
    if not title:
        return True
    cleaned = title.strip()
    if not cleaned:
        return True
    if "@" in cleaned:
        return True
    if cleaned.lower().startswith("http://") or cleaned.lower().startswith("https://"):
        return True
    if len(cleaned) < 6 and " " not in cleaned:
        return True
    return False


@lru_cache(maxsize=4096)
def url_is_reachable(url: str) -> bool:
    if not is_public_http_url(url):
        return False
    try:
        with httpx.Client(follow_redirects=True, timeout=5.0, headers={"User-Agent": "ConvocaRadar/1.0"}) as client:
            response = client.head(url)
            if response.status_code in {405, 501}:
                response = client.get(url)
            return 200 <= response.status_code < 400
    except httpx.HTTPError:
        return False


def candidate_external_id(source: Source, url: str | None, title: str) -> str:
    fingerprint = hashlib.sha256(f"{url or ''}|{title}".encode("utf-8")).hexdigest()[:16]
    return f"{source.key}-{fingerprint}"


async def _scrape_source_candidates(source: Source) -> list[OpportunityCreate]:
    connector = connector_for(source.key, source.base_url, source.source_type)
    raw = await connector.fetch()
    candidates = await connector.parse(raw)
    opportunities: list[OpportunityCreate] = []
    for candidate in candidates:
        if is_noise_title(candidate.title):
            continue
        validation = await connector.validate(candidate)
        if not validation.ok:
            continue
        opportunities.append(
            OpportunityCreate(
                source_id=source.id,
                external_id=candidate_external_id(source, candidate.official_url, candidate.title),
                title=candidate.title,
                entity=candidate.entity,
                country=candidate.country,
                region=source.region,
                language=candidate.language,
                categories=candidate.categories,
                topics=candidate.topics,
                description=candidate.summary or candidate.title,
                summary=candidate.summary or candidate.title,
                raw_text=candidate.raw_text,
                official_url=candidate.official_url,
                open_date=candidate.open_date,
                close_date=candidate.close_date,
                funding_amount_raw=candidate.funding_amount_raw,
                requirements=candidate.requirements,
                confidence_score=candidate.confidence_score,
            )
        )
    return opportunities


def build_opportunity_query(
    organization_id: str,
    *,
    country: str | None = None,
    category: str | None = None,
    status: str | None = None,
    source_id: str | None = None,
    priority: str | None = None,
    search: str | None = None,
) -> Select[tuple[Opportunity]]:
    stmt = select(Opportunity).where(
        or_(Opportunity.organization_id == organization_id, Opportunity.organization_id.is_(None))
    )
    if country:
        stmt = stmt.where(Opportunity.country == country)
    if category:
        stmt = stmt.where(Opportunity.categories.contains([category]))
    if status:
        stmt = stmt.where(Opportunity.status == status)
    if source_id:
        stmt = stmt.where(Opportunity.source_id == source_id)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            or_(
                Opportunity.title.ilike(like),
                Opportunity.entity.ilike(like),
                Opportunity.summary.ilike(like),
                Opportunity.description.ilike(like),
                Opportunity.raw_text.ilike(like),
                Opportunity.official_url.ilike(like),
                Opportunity.application_url.ilike(like),
            )
        )
    stmt = stmt.where(~Opportunity.title.ilike("%@%"))
    stmt = stmt.where(~Opportunity.title.ilike("http%"))
    if priority:
        stmt = stmt.join(OpportunityScore, OpportunityScore.opportunity_id == Opportunity.id).where(
            OpportunityScore.organization_id == organization_id,
            OpportunityScore.priority == priority,
        )
    return stmt.order_by(Opportunity.close_date.asc().nullslast(), Opportunity.created_at.desc())


def create_opportunity(db: Session, data: OpportunityCreate, organization_id: str | None = None) -> Opportunity:
    data = enrich_opportunity_payload(data)
    normalized_title = data.title.strip()
    slug = slugify(f"{normalized_title}-{data.entity}")
    score_organization_id = organization_id
    if data.official_url and not url_is_reachable(data.official_url):
        data = data.model_copy(update={"official_url": None})
    if data.application_url and not url_is_reachable(data.application_url):
        data = data.model_copy(update={"application_url": None})
    if data.external_id and data.source_id:
        existing_by_external_id = db.scalar(
            select(Opportunity).where(
                Opportunity.source_id == data.source_id,
                Opportunity.external_id == data.external_id,
                or_(Opportunity.organization_id == organization_id, Opportunity.organization_id.is_(None)),
            )
        )
        if existing_by_external_id:
            existing_by_external_id.last_seen_at = datetime.now(UTC).replace(tzinfo=None)
            existing_by_external_id.summary = data.summary or existing_by_external_id.summary
            existing_by_external_id.status = inferred_opportunity_status(
                data.close_date,
                " ".join([data.summary, data.raw_text]),
            )
            score_organization_id = existing_by_external_id.organization_id or score_organization_id
            upsert_opportunity_embedding(db, existing_by_external_id)
            if score_organization_id:
                profile = db.scalar(select(OrganizationProfile).where(OrganizationProfile.organization_id == score_organization_id))
                if profile:
                    calculate_score(db, existing_by_external_id, profile)
            return existing_by_external_id
    existing = db.scalar(
        select(Opportunity).where(
            Opportunity.slug == slug,
            Opportunity.entity == data.entity,
            Opportunity.close_date == data.close_date,
        )
    )
    if existing:
        existing.last_seen_at = datetime.now(UTC).replace(tzinfo=None)
        existing.summary = data.summary or existing.summary
        existing.status = inferred_opportunity_status(data.close_date, " ".join([data.summary, data.raw_text]))
        return existing
    values = data.model_dump()
    values.pop("title", None)
    if values.get("language") in {None, "", "auto"}:
        values["language"] = infer_language(" ".join([data.title, data.summary, data.raw_text, data.description]), fallback="es")
    opportunity = Opportunity(
        **values,
        organization_id=organization_id,
        title=normalized_title,
        slug=slug,
        status=inferred_opportunity_status(data.close_date, " ".join([data.summary, data.raw_text])),
    )
    db.add(opportunity)
    db.flush()
    upsert_opportunity_embedding(db, opportunity)
    if score_organization_id:
        profile = db.scalar(select(OrganizationProfile).where(OrganizationProfile.organization_id == score_organization_id))
        if profile:
            calculate_score(db, opportunity, profile)
    return opportunity


def execute_source_run_locally(db: Session, source: Source, organization_id: str | None = None) -> SourceRun:
    started_at = datetime.now(UTC).replace(tzinfo=None)
    run = SourceRun(
        source_id=source.id,
        status="running",
        started_at=started_at,
        logs=[{"level": "info", "message": "Scraping MVP started"}],
    )
    source.last_run_at = started_at
    db.add(run)
    db.flush()
    task = Task(
        organization_id=organization_id or source.organization_id,
        source_run_id=run.id,
        task_type="scrape_source",
        provider="local",
        status="running",
        started_at=started_at,
        payload={"source_key": source.key, "base_url": source.base_url, "source_type": source.source_type},
    )
    db.add(task)
    db.flush()
    try:
        validate_source_url(source)
        opportunities = asyncio.run(_scrape_source_candidates(source))
        created = 0
        updated = 0
        for opportunity_data in opportunities:
            opportunity = create_opportunity(db, opportunity_data, organization_id=organization_id)
            if opportunity.first_seen_at == opportunity.last_seen_at:
                created += 1
            else:
                updated += 1
        db.flush()
        finished_at = datetime.now(UTC).replace(tzinfo=None)
        run.status = "success"
        run.finished_at = finished_at
        run.items_found = len(opportunities)
        run.items_created = created
        run.items_updated = updated
        run.logs = [
            *run.logs,
            {"level": "info", "message": "Local connector executed", "task_id": task.id},
            {"level": "info", "message": "Candidates normalized", "items_found": len(opportunities)},
        ]
        task.status = "success"
        task.finished_at = finished_at
        task.result = {"items_found": len(opportunities), "items_created": created, "items_updated": updated}
        source.last_success_at = finished_at
        source.last_error = None
        if len(opportunities) == 0:
            create_source_health_alert(
                db,
                source,
                reason="no se detectaron oportunidades nuevas en la ultima corrida",
            )
    except Exception as exc:
        finished_at = datetime.now(UTC).replace(tzinfo=None)
        run.status = "failed"
        run.finished_at = finished_at
        run.items_failed = 1
        run.error_message = str(exc)
        run.logs = [*run.logs, {"level": "error", "message": str(exc)}]
        task.status = "failed"
        task.finished_at = finished_at
        task.error_message = str(exc)
        task.result = {"items_failed": 1}
        source.last_error = str(exc)
        create_source_health_alert(db, source, reason=str(exc))
    return run


def calculate_score(db: Session, opportunity: Opportunity, profile: OrganizationProfile) -> OpportunityScore:
    score = 0.0
    reasons: list[str] = []
    warnings: list[str] = []
    profile_areas = {item.lower() for item in profile.areas_of_interest}
    opp_topics = {item.lower() for item in [*opportunity.categories, *opportunity.topics]}

    if opportunity.country == profile.country or profile.eligible_international:
        score += 15
        reasons.append("La región de la convocatoria es compatible con el perfil.")
    else:
        warnings.append("La convocatoria puede tener restricciones regionales.")

    if profile.organization_type in [item.lower() for item in opportunity.eligible_applicants] or not opportunity.eligible_applicants:
        score += 20
        reasons.append("El tipo de organización parece elegible.")
    else:
        warnings.append("El tipo de organización no aparece explícitamente como beneficiario.")

    overlap = profile_areas.intersection(opp_topics)
    if overlap:
        score += 20
        reasons.append(f"Coincidencia temática: {', '.join(sorted(overlap))}.")
    elif not profile_areas:
        score += 8
        warnings.append("El perfil no tiene áreas de interés suficientes para una comparación fuerte.")

    if opportunity.funding_amount_value:
        score += 10
        if profile.max_funding_amount and opportunity.funding_amount_value > profile.max_funding_amount:
            warnings.append("El monto supera el rango preferido configurado.")
        else:
            score += 10
            reasons.append("El monto encaja con las preferencias declaradas.")

    if opportunity.status == OpportunityStatus.open.value:
        score += 10
        reasons.append("La convocatoria está abierta.")
    elif opportunity.status == OpportunityStatus.closing_soon.value:
        score += 5
        warnings.append("La convocatoria cierra pronto.")

    if opportunity.requirements:
        score += 10
        reasons.append("Hay requisitos identificados para planear la postulación.")

    if score < 40 and not warnings:
        warnings.append("La compatibilidad es baja con los datos disponibles.")

    result = OpportunityScore(
        opportunity_id=opportunity.id,
        organization_id=profile.organization_id,
        score=min(score, 100),
        priority=priority_for_score(min(score, 100)),
        reasons=reasons,
        warnings=warnings,
    )
    db.add(result)
    return result


def generate_report_html(title: str, organization: Organization, opportunities: list[Opportunity]) -> str:
    total = len(opportunities)
    open_count = sum(1 for item in opportunities if item.status == OpportunityStatus.open.value)
    closing_soon_count = sum(1 for item in opportunities if item.status == OpportunityStatus.closing_soon.value)
    closed_count = sum(1 for item in opportunities if item.status == OpportunityStatus.closed.value)
    unknown_count = sum(1 for item in opportunities if item.status == OpportunityStatus.unknown.value)
    with_source = sum(1 for item in opportunities if item.source_id)
    with_summary = sum(1 for item in opportunities if item.summary.strip())
    with_amount = sum(1 for item in opportunities if item.funding_amount_raw or item.funding_amount_value)
    with_date = sum(1 for item in opportunities if item.close_date)
    countries = sorted({item.country for item in opportunities if item.country})
    categories = sorted({category for item in opportunities for category in item.categories if category})
    top_countries = sorted(
        ((country, sum(1 for item in opportunities if item.country == country)) for country in countries),
        key=lambda entry: (-entry[1], entry[0]),
    )[:6]
    top_categories = sorted(
        ((category, sum(1 for item in opportunities if category in item.categories)) for category in categories),
        key=lambda entry: (-entry[1], entry[0]),
    )[:6]

    def _format_amount(item: Opportunity) -> str:
        if item.funding_amount_raw:
            return item.funding_amount_raw
        if item.funding_amount_value is not None:
            return f"{item.funding_amount_value:,.0f}".replace(",", ".")
        return "No disponible"

    def _link_for(item: Opportunity) -> str:
        for candidate in (item.official_url, item.application_url):
            if candidate and url_is_reachable(candidate):
                return candidate
        return "#"

    featured = opportunities[:9]
    featured_cards = "\n".join(
        f"""
        <article class=\"story-card\">
          <div class=\"story-card__header\">
            <span class=\"story-card__eyebrow\">{escape(item.status.replace('_', ' '))}</span>
            <span class=\"story-card__meta\">{escape(item.country)}</span>
          </div>
          <h3 class=\"story-card__title\">{f'<a href=\"{escape(_link_for(item))}\" target=\"_blank\" rel=\"noopener noreferrer\">{escape(item.title)}</a>' if _link_for(item) != '#' else escape(item.title)}</h3>
          <p class=\"story-card__body\">{escape(item.summary or item.description or 'Sin resumen disponible.')}</p>
          <dl class=\"story-card__facts\">
            <div><dt>Entidad</dt><dd>{escape(item.entity)}</dd></div>
            <div><dt>Cierre</dt><dd>{escape(item.close_date.date().isoformat() if item.close_date else 'Sin fecha')}</dd></div>
            <div><dt>Monto</dt><dd>{escape(_format_amount(item))}</dd></div>
            <div><dt>Fuente</dt><dd>{escape(item.source_id or 'Sin fuente')}</dd></div>
          </dl>
          <div class=\"story-card__actions\">
            {f'<a class=\"link-button\" href=\"{escape(_link_for(item))}\" target=\"_blank\" rel=\"noopener noreferrer\">Ver convocatoria</a>' if _link_for(item) != '#' else ''}
            {f'<a class=\"link-button link-button--ghost\" href=\"{escape(item.application_url)}\" target=\"_blank\" rel=\"noopener noreferrer\">Postular</a>' if item.application_url and url_is_reachable(item.application_url) else ''}
          </div>
        </article>
        """
        for item in featured
    )
    rows = "\n".join(
        f"""
        <tr>
          <td class=\"col-title\">
            <a href=\"{escape(_link_for(o))}\" target=\"_blank\" rel=\"noopener noreferrer\">{escape(o.title)}</a>
            <span>{escape((o.summary or o.description or 'Sin resumen disponible.')[:140])}</span>
          </td>
          <td>{escape(o.entity)}</td>
          <td>{escape(o.country)}</td>
          <td><span class=\"status status--{escape(o.status)}\">{escape(o.status)}</span></td>
          <td>{escape(o.close_date.date().isoformat() if o.close_date else 'Sin fecha')}</td>
          <td>{escape(_format_amount(o))}</td>
        </tr>
        """
        for o in opportunities
    )
    country_rows = "\n".join(f"<tr><td>{escape(country)}</td><td>{count}</td></tr>" for country, count in top_countries)
    category_rows = "\n".join(f"<tr><td>{escape(category)}</td><td>{count}</td></tr>" for category, count in top_categories)
    return f"""<!doctype html>
<html lang=\"es\">
<head><meta charset=\"utf-8\"><title>{escape(title)}</title>
<style>
:root {{
  --bg: #f8fafc;
  --surface: rgba(255,255,255,0.92);
  --surface-strong: #ffffff;
  --text: #0f172a;
  --muted: #52617a;
  --border: #d8e1f3;
  --accent: #0d4e5e;
  --accent-soft: rgba(13, 78, 94, 0.09);
  --accent-2: #4f46e5;
  --success: #15803d;
  --warning: #b45309;
  --danger: #b91c1c;
  --shadow: 0 18px 42px -18px rgba(15, 23, 42, 0.24);
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  padding: 32px 18px 48px;
  font-family: Inter, Arial, sans-serif;
  color: var(--text);
  background:
    radial-gradient(circle at top, rgba(13, 78, 94, 0.1), transparent 34%),
    linear-gradient(180deg, #faf8ff 0%, #eef2ff 100%);
  line-height: 1.5;
}}
a {{ color: inherit; text-decoration: none; }}
.shell {{ max-width: 1240px; margin: 0 auto; }}
.hero {{
  position: relative;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 24px;
  background: linear-gradient(135deg, rgba(255,255,255,0.92), rgba(242,243,255,0.92));
  box-shadow: var(--shadow);
  padding: 28px;
}}
.hero::after {{
  content: "";
  position: absolute;
  inset: 0;
  background:
    radial-gradient(circle at top right, rgba(79, 70, 229, 0.12), transparent 28%),
    radial-gradient(circle at bottom left, rgba(13, 78, 94, 0.12), transparent 24%);
  pointer-events: none;
}}
.hero__inner {{ position: relative; z-index: 1; display: grid; gap: 18px; }}
.eyebrow {{
  display: inline-flex;
  align-items: center;
  gap: 8px;
  width: fit-content;
  padding: 7px 12px;
  border-radius: 999px;
  border: 1px solid rgba(13, 78, 94, 0.16);
  background: rgba(13, 78, 94, 0.06);
  color: var(--accent);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}}
h1 {{
  margin: 0;
  font-size: clamp(2rem, 4vw, 3.5rem);
  line-height: 1.03;
  letter-spacing: -0.03em;
  font-family: "Space Grotesk", "Inter", Arial, sans-serif;
}}
.hero__lead {{
  max-width: 720px;
  font-size: 1.06rem;
  color: var(--muted);
  margin: 0;
}}
.hero__toolbar {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 4px; }}
.button {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 42px;
  padding: 0 16px;
  border-radius: 12px;
  border: 1px solid var(--border);
  background: var(--surface-strong);
  color: var(--text);
  font-weight: 600;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.04);
}}
.button--primary {{ border-color: transparent; background: linear-gradient(135deg, var(--accent), #0f766e); color: #fff; }}
.button--ghost {{ background: rgba(255,255,255,0.8); }}
.grid-stats {{
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin: 18px 0 32px;
}}
.stat {{
  border: 1px solid var(--border);
  border-radius: 18px;
  padding: 16px;
  background: var(--surface);
}}
.stat span {{
  display: block;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--muted);
}}
.stat strong {{ display: block; margin-top: 6px; font-size: 28px; line-height: 1; color: var(--text); }}
.section {{
  margin-top: 26px;
  border: 1px solid var(--border);
  border-radius: 22px;
  background: var(--surface);
  box-shadow: 0 10px 28px -18px rgba(15, 23, 42, 0.22);
  overflow: hidden;
}}
.section__head {{ padding: 20px 22px 0; }}
.section__title {{ margin: 0; font-family: "Space Grotesk", "Inter", Arial, sans-serif; font-size: 1.35rem; }}
.section__subtitle {{ margin: 6px 0 0; color: var(--muted); font-size: 0.96rem; }}
.section__body {{ padding: 20px 22px 24px; }}
.grid-2 {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }}
.story-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }}
.story-card {{
  border: 1px solid var(--border);
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(255,255,255,0.96), rgba(248,250,252,0.98));
  padding: 18px;
  min-height: 100%;
}}
.story-card__header {{ display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }}
.story-card__eyebrow {{
  padding: 4px 8px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}}
.story-card__meta {{ color: var(--muted); font-size: 12px; }}
.story-card__title {{ margin: 0 0 10px; font-size: 1.12rem; line-height: 1.3; }}
.story-card__title a:hover {{ color: var(--accent); }}
.story-card__body {{ margin: 0; color: var(--muted); font-size: 0.96rem; }}
.story-card__facts {{
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 14px;
  margin: 16px 0 0;
}}
.story-card__facts div {{ padding-top: 10px; border-top: 1px solid rgba(82, 97, 122, 0.15); }}
.story-card__facts dt {{ font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; font-weight: 700; }}
.story-card__facts dd {{ margin: 4px 0 0; font-size: 0.93rem; font-weight: 600; color: var(--text); }}
.story-card__actions {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 16px; }}
.link-button {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 38px;
  padding: 0 14px;
  border-radius: 11px;
  background: var(--accent);
  color: #fff;
  font-size: 0.88rem;
  font-weight: 700;
}}
.link-button--ghost {{
  background: rgba(79, 70, 229, 0.09);
  color: var(--accent-2);
  border: 1px solid rgba(79, 70, 229, 0.18);
}}
table {{ width: 100%; border-collapse: collapse; overflow: hidden; }}
thead th {{
  background: #f2f5fb;
  color: #334155;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  border-bottom: 1px solid var(--border);
  text-align: left;
  padding: 12px 14px;
}}
tbody td {{ border-bottom: 1px solid rgba(216, 225, 243, 0.9); padding: 13px 14px; font-size: 13px; vertical-align: top; }}
tbody tr:hover {{ background: rgba(13, 78, 94, 0.03); }}
.col-title a {{ display: block; font-weight: 700; color: var(--text); }}
.col-title span {{ display: block; margin-top: 4px; color: var(--muted); font-size: 12px; line-height: 1.35; }}
.status {{
  display: inline-flex;
  align-items: center;
  padding: 4px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  text-transform: capitalize;
}}
.status--open {{ background: rgba(21, 128, 61, 0.1); color: var(--success); }}
.status--closing_soon {{ background: rgba(180, 83, 9, 0.1); color: var(--warning); }}
.status--closed {{ background: rgba(100, 116, 139, 0.12); color: #475569; }}
.status--unknown {{ background: rgba(100, 116, 139, 0.12); color: #475569; }}
.status--draft {{ background: rgba(79, 70, 229, 0.1); color: var(--accent-2); }}
.status--archived {{ background: rgba(100, 116, 139, 0.12); color: #475569; }}
.note {{ font-size: 12px; color: var(--muted); margin: 0; }}
.stack {{ display: grid; gap: 18px; }}
.grid-table-wrap {{ overflow-x: auto; }}
@media (max-width: 1100px) {{
  .grid-stats, .story-grid, .grid-2 {{ grid-template-columns: 1fr 1fr; }}
}}
@media (max-width: 760px) {{
  body {{ padding: 18px 12px 28px; }}
  .hero, .section {{ border-radius: 18px; }}
  .grid-stats, .story-grid, .grid-2 {{ grid-template-columns: 1fr; }}
  .story-card__facts {{ grid-template-columns: 1fr; }}
}}
</style></head>
<body>
<div class="shell">
<section class="hero">
  <div class="hero__inner">
    <div class="eyebrow">ConvocaRadar IA</div>
    <h1>{escape(title)}</h1>
    <p class="hero__lead">Organización: {escape(organization.name)} · Generado: {datetime.now(UTC).date().isoformat()} · Reporte ejecutivo de oportunidades filtradas y priorizadas para revisión institucional.</p>
    <div class="hero__toolbar">
      <a class="button button--primary" href="#oportunidades">Ver convocatorias</a>
      <a class="button" href="#resumen">Resumen ejecutivo</a>
      <a class="button button--ghost" href="#metodologia">Metodología</a>
    </div>
  </div>
</section>

<section class="grid-stats" aria-label="Resumen de indicadores">
  <div class="stat"><span>Total oportunidades</span><strong>{total}</strong></div>
  <div class="stat"><span>Abiertas</span><strong>{open_count}</strong></div>
  <div class="stat"><span>Por cerrar</span><strong>{closing_soon_count}</strong></div>
  <div class="stat"><span>Con fecha de cierre</span><strong>{with_date}</strong></div>
  <div class="stat"><span>Con fuente</span><strong>{with_source}</strong></div>
  <div class="stat"><span>Con resumen</span><strong>{with_summary}</strong></div>
  <div class="stat"><span>Con monto</span><strong>{with_amount}</strong></div>
  <div class="stat"><span>Sin validar</span><strong>{unknown_count}</strong></div>
</section>

<section class="section" id="resumen">
  <div class="section__head">
    <h2 class="section__title">Resumen ejecutivo</h2>
    <p class="section__subtitle">Lectura rápida del estado de la cartera de convocatorias.</p>
  </div>
  <div class="section__body stack">
    <p>Se identificaron {total} oportunidades relevantes para revisión institucional. {closed_count} ya están cerradas y {closing_soon_count} requieren atención cercana.</p>
    <div class="grid-2">
      <div>
        <table><thead><tr><th>Principales países</th><th>Oportunidades</th></tr></thead><tbody>{country_rows or '<tr><td colspan="2">Sin datos</td></tr>'}</tbody></table>
      </div>
      <div>
        <table><thead><tr><th>Principales categorías</th><th>Oportunidades</th></tr></thead><tbody>{category_rows or '<tr><td colspan="2">Sin datos</td></tr>'}</tbody></table>
      </div>
    </div>
  </div>
</section>

<section class="section">
  <div class="section__head">
    <h2 class="section__title">Panorama visual</h2>
    <p class="section__subtitle">Bloques editoriales para revisar la cartera con más contexto.</p>
  </div>
  <div class="section__body">
    <div class="story-grid">
      {featured_cards or '<div class="story-card"><p class="story-card__body">No hay convocatorias para mostrar.</p></div>'}
    </div>
  </div>
</section>

<section class="section" id="oportunidades">
  <div class="section__head">
    <h2 class="section__title">Convocatorias recomendadas</h2>
    <p class="section__subtitle">Cada título enlaza la convocatoria oficial para consultar y actuar directamente.</p>
  </div>
  <div class="section__body grid-table-wrap">
    <table>
      <thead><tr><th>Título</th><th>Entidad</th><th>País</th><th>Estado</th><th>Cierre</th><th>Monto</th></tr></thead>
      <tbody>{rows or '<tr><td colspan="6">Sin convocatorias disponibles</td></tr>'}</tbody>
    </table>
  </div>
</section>

<section class="section" id="metodologia">
  <div class="section__head">
    <h2 class="section__title">Metodología</h2>
    <p class="section__subtitle">Formato listo para lectura ejecutiva, exportación e impresión.</p>
  </div>
  <div class="section__body stack">
    <p>Reporte generado desde fuentes configuradas, con normalización, deduplicación y priorización automática. El archivo PDF se renderiza con Playwright y, si el motor no está disponible, cae a una salida tipográfica de respaldo.</p>
    <p class="note">Cobertura de datos: {with_source} con fuente, {with_summary} con resumen, {with_amount} con monto y {with_date} con fecha de cierre.</p>
  </div>
</section>
</div>
</body></html>"""


async def _render_pdf_with_playwright(html: str) -> bytes:
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 1800})
            await page.set_content(html, wait_until="load")
            await page.emulate_media(media="print")
            return await page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "18mm", "right": "14mm", "bottom": "18mm", "left": "14mm"},
            )
        finally:
            await browser.close()


def export_csv(opportunities: list[Opportunity]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["title", "entity", "country", "status", "close_date", "funding_amount", "official_url"])
    for item in opportunities:
        writer.writerow([
            item.title,
            item.entity,
            item.country,
            item.status,
            item.close_date.date().isoformat() if item.close_date else "",
            item.funding_amount_raw or item.funding_amount_value or "",
            item.official_url or "",
        ])
    return output.getvalue()


def export_xlsx(opportunities: list[Opportunity]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Convocatorias"
    sheet.append(["Titulo", "Entidad", "Pais", "Estado", "Cierre", "Monto", "URL oficial"])
    for item in opportunities:
        sheet.append(
            [
                item.title,
                item.entity,
                item.country,
                item.status,
                item.close_date.date().isoformat() if item.close_date else "",
                item.funding_amount_raw or item.funding_amount_value or "",
                item.official_url or "",
            ]
        )
    for column_cells in sheet.columns:
        max_length = max(len(str(cell.value or "")) for cell in column_cells)
        sheet.column_dimensions[column_cells[0].column_letter].width = min(max(max_length + 2, 12), 48)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def export_pdf(title: str, organization: Organization, opportunities: list[Opportunity]) -> bytes:
    html = generate_report_html(title, organization, opportunities)
    try:
        return asyncio.run(_render_pdf_with_playwright(html))
    except Exception:
        pass

    output = io.BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, title=title, leftMargin=36, rightMargin=36)
    styles = getSampleStyleSheet()
    story: list[object] = [
        Paragraph(title, styles["Title"]),
        Paragraph(f"Organización: {organization.name}", styles["Normal"]),
        Paragraph(f"Generado: {datetime.now(UTC).date().isoformat()}", styles["Normal"]),
        Spacer(1, 16),
        Paragraph("Resumen ejecutivo", styles["Heading2"]),
        Paragraph(f"Se identificaron {len(opportunities)} oportunidades para revisión institucional.", styles["BodyText"]),
        Spacer(1, 12),
        Paragraph("Convocatorias", styles["Heading2"]),
    ]
    data = [["Título", "Entidad", "País", "Estado", "Cierre", "Monto"]]
    for item in opportunities[:40]:
        data.append(
            [
                Paragraph(escape(item.title), styles["BodyText"]),
                Paragraph(escape(item.entity), styles["BodyText"]),
                item.country,
                item.status,
                item.close_date.date().isoformat() if item.close_date else "Sin fecha",
                item.funding_amount_raw or (str(item.funding_amount_value) if item.funding_amount_value is not None else "No disponible"),
            ]
        )
    table = Table(data, colWidths=[165, 120, 70, 60, 60, 85], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f3f5")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(table)
    story.extend(
        [
            Spacer(1, 14),
            Paragraph("Metodología", styles["Heading2"]),
            Paragraph(
                "Reporte generado desde fuentes configuradas, con normalización, deduplicación y priorización automática.",
                styles["BodyText"],
            ),
        ]
    )
    document.build(story)
    return output.getvalue()


def create_heuristic_extraction(text: str) -> dict[str, object]:
    return build_local_extraction(text)


def create_ai_extraction(text: str) -> dict[str, object]:
    extraction = asyncio.run(extract_opportunity_structured(text))
    return extraction.data


def summarize_text(text: str) -> str:
    return summarize_opportunity_text(text)


def count_query(db: Session, stmt: Select[tuple[Opportunity]]) -> int:
    return db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

