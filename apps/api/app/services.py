from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import ipaddress
import json
import re
from datetime import UTC, datetime, timedelta
from html import escape
from functools import lru_cache
from urllib.parse import urlparse

import httpx
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.config import get_settings
from app.core.ai import (
    build_embedding,
    build_local_extraction,
    compose_embedding_text,
    cosine_similarity,
    embedding_model_version,
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
    Role,
    Source,
    SourceRun,
    Task,
    User,
)
from app.schemas import (
    DashboardBreakdownItem,
    DashboardDataCoverage,
    DashboardSourceAlert,
    HealthKpis,
    OpportunityCreate,
    PipelineOpportunityItem,
    SourceHealthRead,
    TriageOpportunityItem,
)


def connector_for(source_key: str, base_url: str | None = None, source_type: str | None = None, *, entity_name: str | None = None, default_country: str | None = None, default_categories: list[str] | None = None):
    from app.connectors.factory import connector_for as worker_connector_for

    return worker_connector_for(source_key, base_url, source_type, entity_name=entity_name, default_country=default_country, default_categories=default_categories)


SLOW_SCRAPE_SOURCE_KEYS = frozenset(
    {
        "innovamos-global-innovation-fund",
        "innovamos-fid",
        "eu-funding-tenders",
        "minciencias",
        "ukri-opportunities",
        "horizon-europe-sedia",
        "eic-accelerator",
        "procolombia-convocatorias",
        # PR5 follow-up: apc-colombia's HTML page is heavy enough to timeout
        # under Render free's 30-90s scraping window. Regression test
        # apps/api/tests/test_sources.py::test_apc_colombia_is_classified_as_slow_source
        # pins this entry.
        "apc-colombia",
    }
)
SLOW_SCRAPE_SOURCE_TYPES = frozenset({"hybrid"})


def is_slow_scrape_source(source: Source) -> bool:
    return source.key in SLOW_SCRAPE_SOURCE_KEYS or (source.source_type or "") in SLOW_SCRAPE_SOURCE_TYPES


def source_due_for_scraping(source: Source, *, now: datetime | None = None) -> bool:
    current = now or datetime.now(UTC).replace(tzinfo=None)
    frequency = (source.scraping_frequency or "daily").lower()
    if frequency in {"hourly", "every_hour", "daily", "every_day"}:
        return True
    if not source.last_run_at:
        return True
    elapsed = current - source.last_run_at
    if frequency in {"weekly", "every_week"}:
        return elapsed >= timedelta(days=7)
    if frequency in {"monthly", "every_month"}:
        return elapsed >= timedelta(days=28)
    return elapsed >= timedelta(days=1)


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return value or "item"


def normalize_official_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"


def opportunity_dedup_key(official_url: str | None, title: str, raw_text: str = "") -> str | None:
    normalized_url = normalize_official_url(official_url)
    if normalized_url:
        url_patterns = (
            (r"/search-results-detail/(\d+)(?:/|$)", "grants-gov"),
            (r"/opportunity/(\d+)(?:/|$)", "simpler-grants-gov"),
            (r"/topic-details/([^/?#]+)", "eu-topic"),
            (r"/project/id/([^/?#]+)", "cordis-project"),
        )
        for pattern, prefix in url_patterns:
            match = re.search(pattern, normalized_url, flags=re.IGNORECASE)
            if match:
                return f"{prefix}:{match.group(1).lower()}"
        return f"url:{normalized_url}"

    if raw_text:
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            grants_id = str(payload.get("id") or "").strip()
            if grants_id.isdigit():
                return f"grants-gov:{grants_id}"
            number = str(payload.get("number") or "").strip()
            if number:
                return f"grants-gov-number:{number.lower()}"

        number_match = re.search(r"\b(OFOP\d+|TEST-[A-Z0-9-]+)\b", raw_text, flags=re.IGNORECASE)
        if number_match:
            return f"grants-gov-number:{number_match.group(1).lower()}"

    title_key = slugify(title.strip())
    if title_key and title_key != "item":
        return f"title:{title_key}"
    return None


def _organization_opportunity_scope(organization_id: str | None):
    return or_(Opportunity.organization_id == organization_id, Opportunity.organization_id.is_(None))


def find_duplicate_opportunity(
    db: Session,
    data: OpportunityCreate,
    organization_id: str | None,
) -> Opportunity | None:
    scope = _organization_opportunity_scope(organization_id)
    dedup_key = opportunity_dedup_key(data.official_url, data.title, data.raw_text or "")
    if not dedup_key:
        return None

    if dedup_key.startswith("grants-gov:"):
        grants_id = dedup_key.split(":", 1)[1]
        if grants_id.isdigit():
            existing = db.scalar(
                select(Opportunity)
                .where(
                    scope,
                    or_(
                        Opportunity.official_url.ilike(f"%/search-results-detail/{grants_id}%"),
                        Opportunity.official_url.ilike(f"%/opportunity/{grants_id}%"),
                    ),
                )
                .order_by(Opportunity.first_seen_at.asc())
            )
            if existing:
                return existing

    if dedup_key.startswith("grants-gov-number:"):
        grant_number = dedup_key.split(":", 1)[1]
        existing = db.scalar(
            select(Opportunity)
            .where(
                scope,
                or_(
                    Opportunity.raw_text.ilike(f"%{grant_number}%"),
                    Opportunity.summary.ilike(f"%{grant_number}%"),
                ),
            )
            .order_by(Opportunity.first_seen_at.asc())
        )
        if existing:
            return existing

    if dedup_key.startswith("url:"):
        normalized_target = dedup_key[4:]
        candidates = db.scalars(
            select(Opportunity).where(scope, Opportunity.official_url.is_not(None)).order_by(Opportunity.first_seen_at.asc())
        )
        for candidate in candidates:
            if normalize_official_url(candidate.official_url) == normalized_target:
                return candidate
        return None

    if dedup_key.startswith(("eu-topic:", "cordis-project:")):
        token = dedup_key.split(":", 1)[1]
        existing = db.scalar(
            select(Opportunity)
            .where(scope, Opportunity.official_url.ilike(f"%{token}%"))
            .order_by(Opportunity.first_seen_at.asc())
        )
        if existing:
            return existing

    if dedup_key.startswith("title:") and data.close_date:
        existing = db.scalar(
            select(Opportunity)
            .where(
                scope,
                Opportunity.close_date == data.close_date,
                Opportunity.title.ilike(data.title.strip()),
            )
            .order_by(Opportunity.first_seen_at.asc())
        )
        if existing:
            return existing

    return None


def _normalize_survivor_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=None)
    if value.tzinfo is not None:
        return value.replace(tzinfo=None)
    return value


def _opportunity_survivor_key(opportunity: Opportunity) -> tuple[datetime, datetime, str]:
    first_seen = _normalize_survivor_datetime(opportunity.first_seen_at)
    created = _normalize_survivor_datetime(opportunity.created_at) if opportunity.created_at else first_seen
    return (first_seen, created, opportunity.id)


def _get_opportunity_embedding(db: Session, opportunity_id: str) -> OpportunityEmbedding | None:
    existing = db.scalar(select(OpportunityEmbedding).where(OpportunityEmbedding.opportunity_id == opportunity_id))
    if existing:
        return existing
    for pending in db.new:
        if isinstance(pending, OpportunityEmbedding) and pending.opportunity_id == opportunity_id:
            return pending
    return None


def _reassign_opportunity_relations(db: Session, survivor: Opportunity, duplicate: Opportunity) -> None:
    """Reassign all FK relations from duplicate → survivor. Does NOT delete the duplicate."""
    if duplicate.is_favorite and not survivor.is_favorite:
        survivor.is_favorite = True
    if duplicate.user_status not in {"review"} and survivor.user_status == "review":
        survivor.user_status = duplicate.user_status

    for document in db.scalars(select(OpportunityDocument).where(OpportunityDocument.opportunity_id == duplicate.id)):
        document.opportunity_id = survivor.id

    for score in db.scalars(select(OpportunityScore).where(OpportunityScore.opportunity_id == duplicate.id)):
        existing_score = db.scalar(
            select(OpportunityScore).where(
                OpportunityScore.opportunity_id == survivor.id,
                OpportunityScore.organization_id == score.organization_id,
            )
        )
        if existing_score:
            if score.score > existing_score.score:
                existing_score.score = score.score
                existing_score.priority = score.priority
                existing_score.reasons = score.reasons
                existing_score.warnings = score.warnings
            db.delete(score)
        else:
            score.opportunity_id = survivor.id

    duplicate_embedding = db.scalar(select(OpportunityEmbedding).where(OpportunityEmbedding.opportunity_id == duplicate.id))
    if duplicate_embedding:
        survivor_embedding = db.scalar(select(OpportunityEmbedding).where(OpportunityEmbedding.opportunity_id == survivor.id))
        if survivor_embedding:
            db.delete(duplicate_embedding)
        else:
            duplicate_embedding.opportunity_id = survivor.id

    for alert in db.scalars(select(Alert).where(Alert.opportunity_id == duplicate.id)):
        alert.opportunity_id = survivor.id


def _merge_opportunity_records(db: Session, survivor: Opportunity, duplicate: Opportunity) -> None:
    _reassign_opportunity_relations(db, survivor, duplicate)
    db.delete(duplicate)


def deduplicate_opportunities(db: Session, organization_id: str | None = None) -> dict[str, int]:
    scope = _organization_opportunity_scope(organization_id)
    opportunities = list(db.scalars(select(Opportunity).where(scope).order_by(Opportunity.first_seen_at.asc())))
    grouped: dict[str, list[Opportunity]] = {}
    for opportunity in opportunities:
        key = opportunity_dedup_key(opportunity.official_url, opportunity.title, opportunity.raw_text or "") or f"id:{opportunity.id}"
        grouped.setdefault(key, []).append(opportunity)

    groups_merged = 0
    duplicates_removed = 0
    duplicates_to_delete: list[Opportunity] = []

    for group in grouped.values():
        if len(group) < 2:
            continue
        survivor = min(group, key=_opportunity_survivor_key)
        for duplicate in group:
            if duplicate.id == survivor.id:
                continue
            _reassign_opportunity_relations(db, survivor, duplicate)
            duplicates_to_delete.append(duplicate)
            duplicates_removed += 1
        groups_merged += 1

    # Flush all FK reassignments before any deletes to avoid FK constraint violations
    db.flush()

    for duplicate in duplicates_to_delete:
        db.delete(duplicate)
    db.flush()
    return {"groups_merged": groups_merged, "duplicates_removed": duplicates_removed}


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
            .where(User.organization_id == source.organization_id, User.role == Role.admin.value)
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


def _parse_funding_amount(funding_raw: str | None) -> tuple[float | None, str | None]:
    """Parse ``funding_amount_raw`` into (numeric_value, currency_code).

    Handles formats like:
      - ``USD 500,000`` / ``EUR 1.2 million`` / ``COP 5000000``
      - ``$500,000`` / ``$5,000,000 COP`` / ``$1.2M``
      - ``US$ 500,000`` / ``€ 1.200.000``
      - ``5.000.000.000`` (Spanish notation, dots as thousands sep)
    Returns ``(None, None)`` when no pattern matches.
    """
    if not funding_raw:
        return None, None

    text = funding_raw.strip()

    # Detect currency from prefix/suffix
    currency = "USD"  # default
    currency_map = {
        "COP": ["COP", "COL$"],
        "EUR": ["EUR", "€"],
        "GBP": ["GBP", "£"],
        "BRL": ["BRL", "R$"],
        "MXN": ["MXN", "MX$"],
        "USD": ["USD", "US$", "$"],
    }
    upper = text.upper()
    for code, symbols in currency_map.items():
        if any(sym in upper for sym in symbols):
            currency = code
            break

    # Normalize: remove currency symbols and text, normalize Spanish notation
    cleaned = re.sub(r"[^\d,.\s]", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Spanish notation: dots as thousands, commas as decimals → normalize
    if re.search(r"\d\.\d{3}", cleaned):
        cleaned = cleaned.replace(".", "")

    cleaned = cleaned.replace(",", "").strip()

    # Extract numeric value
    numbers = re.findall(r"\d+(?:\.\d+)?", cleaned)
    if not numbers:
        return None, None

    # Take the largest number (covers "USD 500,000 - USD 1,000,000" ranges)
    value = max(float(n) for n in numbers)

    # Handle million/k suffixes
    if re.search(r"(?:million|MM)\b", text, re.IGNORECASE) or text.upper().endswith("M"):
        value *= 1_000_000
    elif re.search(r"(?:\b[kK]\b|[kK]$)", text) and value < 1_000_000:
        value *= 1_000

    return value, currency


def _combined_text(data: OpportunityCreate) -> str:
    """Build a combined text blob from all available fields for regex extraction.

    Many connectors only populate ``raw_text`` with the summary from a list
    page, which rarely contains the close date — that information lives in
    the title, description, or combined text. Merging all fields together
    gives the regex-based ``extract_close_date`` a much better chance.
    """
    return " ".join(
        part
        for part in [data.title, data.summary, data.description, data.raw_text]
        if part
    )


def enrich_opportunity_payload(data: OpportunityCreate) -> OpportunityCreate:
    raw_text = data.raw_text.strip()
    combined = _combined_text(data)
    if not raw_text or len(raw_text) < 120:
        merged = data.model_dump()
        if merged.get("language") in {None, "", "auto"}:
            merged["language"] = infer_language(" ".join([data.title, data.summary, data.raw_text, data.description]), fallback="es")
        # Try regex-based close_date extraction from combined text
        if not merged.get("close_date") and combined:
            from app.connectors.common import extract_close_date
            parsed = extract_close_date(combined)
            if parsed:
                merged["close_date"] = parsed
        return OpportunityCreate(**merged)
    if data.summary and data.categories and data.requirements and data.confidence_score >= 0.75:
        merged = data.model_dump()
        if merged.get("language") in {None, "", "auto"}:
            merged["language"] = infer_language(" ".join([data.title, data.summary, data.raw_text, data.description]), fallback="es")
        # Try regex-based close_date extraction from combined text
        if not merged.get("close_date") and combined:
            from app.connectors.common import extract_close_date
            parsed = extract_close_date(combined)
            if parsed:
                merged["close_date"] = parsed
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
    # Parse funding amount into numeric value + currency
    if not data.funding_amount_value:
        parsed_value, parsed_currency = _parse_funding_amount(merged["funding_amount_raw"])
        if parsed_value is not None:
            merged["funding_amount_value"] = parsed_value
            merged["funding_amount_currency"] = parsed_currency
    merged["language"] = data.language if data.language not in {"", "auto"} else str(extraction.get("language") or infer_language(raw_text, fallback="es"))
    merged["confidence_score"] = round(
        max(float(data.confidence_score), float(extraction.get("confidence") or data.confidence_score)),
        2,
    )
    merged["close_date"] = data.close_date or _parse_ai_close_date(extraction.get("close_date"))
    # Fallback: try regex-based close_date extraction from combined text
    if not merged["close_date"] and combined:
        from app.connectors.common import extract_close_date
        parsed = extract_close_date(combined)
        if parsed:
            merged["close_date"] = parsed
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
    existing = _get_opportunity_embedding(db, opportunity.id)
    if existing:
        existing.organization_id = opportunity.organization_id
        existing.source_text = source_text
        existing.embedding = vector
        existing.model_version = embedding_model_version()
        return existing
    embedding = OpportunityEmbedding(
        opportunity_id=opportunity.id,
        organization_id=opportunity.organization_id,
        source_text=source_text,
        embedding=vector,
        model_version=embedding_model_version(),
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
            existing.model_version = embedding_model_version()
            updated += 1
            continue
        db.add(
            OpportunityEmbedding(
                opportunity_id=opportunity.id,
                organization_id=opportunity.organization_id,
                source_text=source_text,
                embedding=vector,
                model_version=embedding_model_version(),
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
    # Parse funding amount into numeric value + currency if not already set
    if opportunity.funding_amount_raw and not opportunity.funding_amount_value:
        parsed_value, parsed_currency = _parse_funding_amount(opportunity.funding_amount_raw)
        if parsed_value is not None:
            opportunity.funding_amount_value = parsed_value
            opportunity.funding_amount_currency = parsed_currency
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
    """Search opportunities by combining text ILIKE with embedding similarity.

    1. First runs a text ILIKE search on title, entity, country, summary.
    2. Then re-ranks results using embedding cosine similarity when available.
    """
    # Step 1: ILIKE text search (always returns something for common terms)
    text_results = _text_search_opportunities(db, organization_id, query, limit=limit * 3)
    if not text_results:
        return []

    # Step 2: Re-rank with embedding similarity if embeddings exist
    query_vector = build_embedding(query)
    scored: list[tuple[Opportunity, float]] = []
    for opportunity, _ in text_results:
        embedding = db.scalar(select(OpportunityEmbedding).where(OpportunityEmbedding.opportunity_id == opportunity.id))
        if embedding and embedding.embedding:
            similarity = cosine_similarity(query_vector, list(embedding.embedding))
        else:
            similarity = 0.0
        lexical = _lexical_search_score(
            {token for token in re.findall(r"[a-z0-9]+", query.lower()) if token},
            opportunity,
        )
        combined = round(min(1.0, (similarity * 0.6) + (lexical * 0.4)), 4)
        scored.append((opportunity, combined))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:limit]


def _text_search_opportunities(
    db: Session,
    organization_id: str,
    query: str,
    *,
    limit: int = 10,
) -> list[tuple[Opportunity, float]]:
    """Full-text fallback when vector search returns no results.

    Searches title, entity, country, and summary using ILIKE on
    individual query tokens so partial and accented matches work
    (e.g. ``innovacion`` matches ``innovación``).
    """
    scope = or_(Opportunity.organization_id == organization_id, Opportunity.organization_id.is_(None))
    _ACCENT_MAP = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")
    tokens = [t.translate(_ACCENT_MAP) for t in re.findall(r"[a-zA-ZáéíóúñüÁÉÍÓÚÑÜ]+", query) if len(t) >= 2]
    if not tokens:
        return []
    stmt = select(Opportunity).where(scope)
    # Build accent-insensitive filters: for each token, check both the original
    # field and the field with accent characters replaced (so 'innovacion'
    # matches both 'innovación' and 'innovacion').
    from sqlalchemy import func as sa_func
    _unaccent = lambda col: sa_func.replace(sa_func.replace(sa_func.replace(sa_func.replace(
        sa_func.replace(sa_func.replace(sa_func.replace(sa_func.replace(
            sa_func.replace(sa_func.replace(sa_func.replace(sa_func.replace(
                col, "á", "a"), "é", "e"), "í", "i"), "ó", "o"), "ú", "u"),
            "ñ", "n"), "Á", "A"), "É", "E"), "Í", "I"), "Ó", "O"), "Ú", "U"), "Ñ", "N")
    filters = []
    for token in tokens:
        like = f"%{token}%"
        filters.append(
            or_(
                _unaccent(Opportunity.title).ilike(like),
                _unaccent(Opportunity.entity).ilike(like),
                _unaccent(Opportunity.country).ilike(like),
                _unaccent(Opportunity.summary).ilike(like),
            )
        )
    stmt = stmt.where(and_(*filters))
    stmt = stmt.order_by(Opportunity.created_at.desc()).limit(limit)
    rows = list(db.scalars(stmt))
    return [(row, 1.0) for row in rows]


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
    lowered = cleaned.lower()
    if "@" in cleaned:
        return True
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return True
    if len(cleaned) < 6 and " " not in cleaned:
        return True
    if any(marker in lowered for marker in ("color:", "background-color:", "font-weight:", "display:", "justify-content:", ".box-address", ".caja", "budgetyearscolumns")):
        return True
    if "{" in cleaned or "}" in cleaned or "<style" in lowered or "<script" in lowered:
        return True
    # ── Low-quality / auto-generated title patterns ──
    # All-caps titles with code-like fragments (e.g. "FNTCE - 322 - 2025")
    # are almost always scraped noise from poorly structured sources.
    import re
    if cleaned == cleaned.upper() and len(cleaned) > 30:
        # If the title is ALL CAPS and has at least one digit, it's likely
        # a template title. Allow short acronyms (<=30 chars) through.
        if re.search(r"[A-Z]{3,}\s*[-–—]\s*\d{2,}", cleaned):
            return True
    # Repeated year pattern: "2025 ... 2025" or "2025-2025"
    years = re.findall(r"\b(20\d{2})\b", cleaned)
    if len(years) >= 2 and len(set(years)) <= 2:
        return True
    # Titles that are >80% uppercase (screaming template titles)
    upper_ratio = sum(1 for c in cleaned if c.isupper()) / max(len(cleaned), 1)
    if upper_ratio > 0.8 and len(cleaned) > 60 and re.search(r"\b(20\d{2})\b", cleaned):
        return True
    # Generic template markers: "CONVOCATORIA" + code, "AVISO", "LICITACIÓN", etc.
    if re.search(
        r"\b(CONVOCATORIA|AVISO|LICITACION|LICITACIÓN|CONCURSO|PROCESO)\b",
        cleaned,
        re.IGNORECASE,
    ) and re.search(r"[A-Z]{3,}\s*[-–—]\s*\d{3,}", cleaned):
        return True
    # Multi-language scraped noise: "Cliquer ici", "click here", "Read more", PDF redirects
    if re.search(r"\b(cliquer ici|click here|read more|download pdf|view pdf|pdf)\b", lowered):
        return True
    return False


def is_noise_payload(*parts: str | None) -> bool:
    title = parts[0] if parts else None
    if is_noise_title(title):
        return True
    text = " ".join(part.strip() for part in parts if part and part.strip())
    return any(
        marker in text.lower()
        for marker in (
            "color: white",
            "background-color:",
            "font-weight: bold",
            "text-decoration: underline",
            "display: flex",
            "justify-content: center",
        )
    )


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


def candidate_external_id(
    source: Source,
    url: str | None,
    title: str,
    raw_text: str = "",
) -> str:
    dedup_key = opportunity_dedup_key(url, title, raw_text)
    if dedup_key:
        fingerprint = hashlib.sha256(dedup_key.encode("utf-8")).hexdigest()[:16]
        return f"dedup-{fingerprint}"
    fingerprint = hashlib.sha256(f"{url or ''}|{title}".encode("utf-8")).hexdigest()[:16]
    return f"{source.key}-{fingerprint}"


async def _scrape_source_candidates(source: Source, stats: dict[str, object] | None = None) -> list[OpportunityCreate]:
    connector = connector_for(
        source.key, source.base_url, source.source_type,
        entity_name=source.name,
        default_country=source.country,
        default_categories=source.category,
    )
    raw = await connector.fetch()
    if stats is not None:
        stats["raw_url"] = raw.url
        stats["raw_content_type"] = raw.content_type
        stats["raw_content_length"] = len(raw.content or "")
    candidates = await connector.parse(raw)
    if not candidates and source.key in {"grants-gov", "grants-gov-rss", "grants-gov-forecast", "simpler-grants"}:
        fallback_connector = connector_for(source.key, None, source.source_type)
        fallback_raw = await fallback_connector.fetch()
        fallback_candidates = await fallback_connector.parse(fallback_raw)
        if stats is not None:
            stats["fallback_raw_url"] = fallback_raw.url
            stats["fallback_raw_content_type"] = fallback_raw.content_type
            stats["fallback_raw_content_length"] = len(fallback_raw.content or "")
            stats["fallback_candidates_parsed"] = len(fallback_candidates)
        if fallback_candidates:
            connector = fallback_connector
            candidates = fallback_candidates
    if stats is not None:
        stats["candidates_parsed"] = len(candidates)
    opportunities: list[OpportunityCreate] = []
    noise_rejected = 0
    validation_rejected = 0
    validation_reasons: list[str] = []
    for candidate in candidates:
        if is_noise_payload(candidate.title, candidate.summary, candidate.raw_text):
            noise_rejected += 1
            continue
        validation = await connector.validate(candidate)
        if not validation.ok:
            validation_rejected += 1
            if len(validation_reasons) < 5:
                validation_reasons.append(validation.reason or "sin razon")
            continue
        opportunities.append(
            OpportunityCreate(
                source_id=source.id,
                external_id=candidate_external_id(source, candidate.official_url, candidate.title, candidate.raw_text or ""),
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
    if stats is not None:
        stats["noise_rejected"] = noise_rejected
        stats["validation_rejected"] = validation_rejected
        stats["validation_reasons"] = validation_reasons
        stats["opportunities_normalized"] = len(opportunities)
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
    stmt = stmt.where(
        ~Opportunity.title.ilike("%color:%"),
        ~Opportunity.title.ilike("%background-color:%"),
        ~Opportunity.title.ilike("%font-weight:%"),
        ~Opportunity.title.ilike("%display:%"),
        ~Opportunity.title.ilike("%justify-content:%"),
        ~Opportunity.title.ilike("%budgetYearsColumns%"),
        ~Opportunity.title.ilike("%plannedOpeningDate%"),
        ~Opportunity.title.ilike("%deadlineDate%"),
        ~Opportunity.title.ilike("%expectedGrants%"),
    )
    return stmt.order_by(Opportunity.close_date.asc().nullslast(), Opportunity.created_at.desc())


def create_opportunity(db: Session, data: OpportunityCreate, organization_id: str | None = None) -> Opportunity:
    data = enrich_opportunity_payload(data)
    normalized_title = data.title.strip()
    if is_noise_payload(normalized_title, data.summary, data.raw_text):
        raise ValueError("Opportunity title looks like scraping noise")
    slug = slugify(f"{normalized_title}-{data.entity}")
    score_organization_id = organization_id
    if data.official_url and not url_is_reachable(data.official_url):
        data = data.model_copy(update={"official_url": None})
    if data.application_url and not url_is_reachable(data.application_url):
        data = data.model_copy(update={"application_url": None})

    def apply_scraped_values(opportunity: Opportunity) -> Opportunity:
        opportunity.last_seen_at = datetime.now(UTC).replace(tzinfo=None)
        opportunity.title = normalized_title
        opportunity.entity = data.entity
        opportunity.country = data.country
        opportunity.region = data.region
        opportunity.language = data.language
        opportunity.categories = list(data.categories)
        opportunity.topics = list(data.topics)
        opportunity.description = data.description
        opportunity.summary = data.summary or data.description or opportunity.summary
        opportunity.raw_text = data.raw_text or opportunity.raw_text
        opportunity.official_url = data.official_url
        opportunity.application_url = data.application_url
        opportunity.open_date = data.open_date
        opportunity.close_date = data.close_date
        opportunity.funding_amount_value = data.funding_amount_value
        opportunity.funding_amount_currency = data.funding_amount_currency
        opportunity.funding_amount_raw = data.funding_amount_raw
        opportunity.eligible_applicants = list(data.eligible_applicants)
        opportunity.requirements = list(data.requirements)
        opportunity.documents_required = list(data.documents_required)
        opportunity.evaluation_criteria = list(data.evaluation_criteria)
        opportunity.restrictions = list(data.restrictions)
        opportunity.risk_flags = list(data.risk_flags)
        opportunity.confidence_score = data.confidence_score
        opportunity.status = inferred_opportunity_status(
            data.close_date,
            " ".join([data.summary, data.raw_text]),
        )
        return opportunity

    if data.external_id and data.source_id:
        existing_by_external_id = db.scalar(
            select(Opportunity).where(
                Opportunity.source_id == data.source_id,
                Opportunity.external_id == data.external_id,
                or_(Opportunity.organization_id == organization_id, Opportunity.organization_id.is_(None)),
            )
        )
        if existing_by_external_id:
            apply_scraped_values(existing_by_external_id)
            score_organization_id = existing_by_external_id.organization_id or score_organization_id
            upsert_opportunity_embedding(db, existing_by_external_id)
            if score_organization_id:
                profile = db.scalar(select(OrganizationProfile).where(OrganizationProfile.organization_id == score_organization_id))
                if profile:
                    calculate_score(db, existing_by_external_id, profile)
            return existing_by_external_id
    if data.external_id and data.external_id.startswith("dedup-"):
        existing_global = db.scalar(
            select(Opportunity)
            .where(
                Opportunity.external_id == data.external_id,
                _organization_opportunity_scope(organization_id),
            )
            .order_by(Opportunity.first_seen_at.asc())
        )
        if existing_global:
            apply_scraped_values(existing_global)
            score_organization_id = existing_global.organization_id or score_organization_id
            upsert_opportunity_embedding(db, existing_global)
            if score_organization_id:
                profile = db.scalar(select(OrganizationProfile).where(OrganizationProfile.organization_id == score_organization_id))
                if profile:
                    calculate_score(db, existing_global, profile)
            return existing_global

    duplicate = find_duplicate_opportunity(db, data, organization_id)
    if duplicate:
        apply_scraped_values(duplicate)
        score_organization_id = duplicate.organization_id or score_organization_id
        upsert_opportunity_embedding(db, duplicate)
        if score_organization_id:
            profile = db.scalar(select(OrganizationProfile).where(OrganizationProfile.organization_id == score_organization_id))
            if profile:
                calculate_score(db, duplicate, profile)
        return duplicate

    if data.source_id and data.official_url:
        existing_by_url = db.scalar(
            select(Opportunity).where(
                Opportunity.source_id == data.source_id,
                Opportunity.official_url == data.official_url,
                or_(Opportunity.organization_id == organization_id, Opportunity.organization_id.is_(None)),
            )
        )
        if existing_by_url:
            apply_scraped_values(existing_by_url)
            score_organization_id = existing_by_url.organization_id or score_organization_id
            upsert_opportunity_embedding(db, existing_by_url)
            if score_organization_id:
                profile = db.scalar(select(OrganizationProfile).where(OrganizationProfile.organization_id == score_organization_id))
                if profile:
                    calculate_score(db, existing_by_url, profile)
            return existing_by_url
    existing = db.scalar(
        select(Opportunity).where(
            Opportunity.slug == slug,
            Opportunity.entity == data.entity,
            Opportunity.close_date == data.close_date,
        )
    )
    if existing:
        apply_scraped_values(existing)
        upsert_opportunity_embedding(db, existing)
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


async def _scrape_source_candidates_with_timeout(
    source: Source, stats: dict[str, object] | None = None
) -> list[OpportunityCreate]:
    settings = get_settings()
    timeout_seconds = max(settings.scraping_max_source_seconds, 30)
    timeout_seconds = min(timeout_seconds, int(settings.per_connector_timeout_seconds))
    try:
        return await asyncio.wait_for(_scrape_source_candidates(source, stats), timeout=timeout_seconds)
    except TimeoutError as exc:
        raise TimeoutError(f"Scrape for source {source.key} exceeded {timeout_seconds}s") from exc


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
    org_id = organization_id or source.organization_id or "00000000-0000-0000-0000-000000000000"
    task = Task(
        organization_id=org_id,
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
        scrape_stats: dict[str, object] = {}
        # FastAPI sync endpoints run in a thread pool. asyncio.run()
        # in a thread can deadlock with the parent event loop on some
        # platforms. Use an explicit fresh loop instead.
        loop = asyncio.new_event_loop()
        try:
            opportunities = loop.run_until_complete(
                _scrape_source_candidates_with_timeout(source, scrape_stats)
            )
        finally:
            loop.close()
        created = 0
        updated = 0
        failed_items = 0
        for opportunity_data in opportunities:
            try:
                opportunity = create_opportunity(db, opportunity_data, organization_id=organization_id)
                if opportunity.first_seen_at == opportunity.last_seen_at:
                    created += 1
                else:
                    updated += 1
            except Exception as exc:
                failed_items += 1
                run.logs.append(
                    {
                        "level": "warning",
                        "message": "Candidate skipped during local persistence",
                        "title": getattr(opportunity_data, "title", ""),
                        "error": str(exc),
                    }
                )
        db.flush()
        finished_at = datetime.now(UTC).replace(tzinfo=None)
        run.status = "degraded" if len(opportunities) == 0 else "success"
        run.finished_at = finished_at
        run.items_found = len(opportunities)
        run.items_created = created
        run.items_updated = updated
        run.items_failed = failed_items
        run.logs = [
            *run.logs,
            {"level": "info", "message": "Local connector executed", "task_id": task.id},
            {"level": "info", "message": "Connector diagnostics", **scrape_stats},
            {"level": "info", "message": "Candidates normalized", "items_found": len(opportunities), "items_failed": failed_items},
        ]
        task.status = run.status
        task.finished_at = finished_at
        task.result = {"items_found": len(opportunities), "items_created": created, "items_updated": updated}
        if len(opportunities) > 0:
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


def _semantic_score(text: str, profile_text: str) -> float:
    """Compare opportunity text with profile text using embedding similarity.
    Uses local hash-based embeddings (no API key required).
    Returns a float in [0, 1] or 0 if empty input.
    """
    if not text.strip() or not profile_text.strip():
        return 0.0
    try:
        opp_vec = build_embedding(text[:2000])
        prof_vec = build_embedding(profile_text[:2000])
        return cosine_similarity(opp_vec, prof_vec)
    except Exception:
        return 0.0


def _compute_score(opportunity: Opportunity, profile: OrganizationProfile) -> dict:
    """Calculate score and reasons WITHOUT touching the DB session.
    Returns ``{"raw": float, "reasons": list[str], "warnings": list[str]}``.
    """
    score = 0.0
    reasons: list[str] = []
    warnings: list[str] = []
    profile_areas = {item.lower() for item in profile.areas_of_interest}
    opp_topics = {item.lower() for item in [*opportunity.categories, *opportunity.topics]}

    # Geographic alignment
    if opportunity.country == profile.country:
        score += 15
        reasons.append(f"La convocatoria es del mismo país ({profile.country}).")
    elif profile.eligible_international:
        score += 10
        reasons.append("La convocatoria es internacional, permitido por el perfil.")
    else:
        score += 5
        warnings.append("La convocatoria puede tener restricciones regionales.")

    # Organization type
    eligible = opportunity.eligible_applicants or []
    if eligible:
        opp_types = {item.lower() for item in eligible}
        if profile.organization_type in opp_types:
            score += 20
            reasons.append("Tu tipo de organización está en los beneficiarios elegibles.")
        elif any(profile.organization_type.startswith(t.rstrip("s")) for t in opp_types):
            score += 15
            reasons.append("Tu organización es parcialmente elegible según los requisitos.")
        else:
            score += 5
            warnings.append("El tipo de organización no aparece como beneficiario explícito.")
    else:
        score += 15
        reasons.append("No hay restricciones explícitas de tipo de organización.")

    # Thematic overlap
    if profile_areas and opp_topics:
        overlap = profile_areas.intersection(opp_topics)
        if overlap:
            ratio = len(overlap) / max(len(profile_areas), 1)
            if ratio >= 0.5:
                score += 25
                reasons.append(f"Alta coincidencia temática: {', '.join(sorted(overlap))}.")
            elif ratio >= 0.25:
                score += 18
                reasons.append(f"Coincidencia temática media: {', '.join(sorted(overlap))}.")
            else:
                score += 12
                reasons.append(f"Coincidencia temática baja: {', '.join(sorted(overlap))}.")
        else:
            score += 5
            warnings.append("Las temáticas no coinciden con tus áreas de interés.")
    elif not profile_areas:
        score += 5
        warnings.append("Completa tus áreas de interés en el perfil.")
    else:
        score += 10
        reasons.append("Coincidencia temática base.")

    # Funding amount
    if opportunity.funding_amount_value:
        if profile.max_funding_amount:
            ratio = opportunity.funding_amount_value / profile.max_funding_amount
            if ratio <= 1.0:
                score += 15 if ratio <= 0.5 else 12
                reasons.append("El monto se ajusta al rango preferido." if ratio <= 1.0 else "")
            else:
                score += 5
                warnings.append("El monto supera el rango preferido.")
        else:
            score += 8
            reasons.append("Monto disponible para revisión.")

    # Deadline proximity
    if opportunity.close_date:
        remaining = (opportunity.close_date - datetime.now(UTC).replace(tzinfo=None)).days
        if remaining > 30:
            score += 5
            reasons.append("Hay tiempo suficiente para preparar la postulación.")
        elif remaining > 7:
            score += 3
        elif remaining >= 0:
            warnings.append("Cierra pronto, se requiere acción inmediata.")

    # Requirements
    if opportunity.requirements:
        score += 3
        reasons.append("Hay requisitos identificados.")
    if opportunity.documents_required:
        score += 2
        reasons.append("Documentos necesarios identificados.")

    if score < 40 and not warnings:
        warnings.append("Compatibilidad baja con los datos disponibles.")

    return {"raw": score, "reasons": reasons, "warnings": warnings}


def calculate_score(db: Session, opportunity: Opportunity, profile: OrganizationProfile) -> OpportunityScore:
    score = _compute_score(opportunity, profile)
    result = OpportunityScore(
        opportunity_id=opportunity.id,
        organization_id=profile.organization_id,
        score=min(round(score["raw"], 1), 100),
        priority=priority_for_score(min(score["raw"], 100)),
        reasons=score["reasons"],
        warnings=score["warnings"],
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
        return item.official_url or item.application_url or "#"

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

    from app.connectors.common import launch_chromium

    async with async_playwright() as playwright:
        browser = await launch_chromium(playwright)
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


# ---------------------------------------------------------------------------
# PR B-1a: /dashboard/triage helpers
# ---------------------------------------------------------------------------


def extract_score_reasons(value: object) -> list[str]:
    """Safely normalize an OpportunityScore.reasons value to a list[str].

    The column is declared as JSON (default=list) and is therefore expected
    to be a list[str] in the steady state. This helper is defensive and
    also handles:

    * ``None`` → ``[]``
    * empty list → ``[]``
    * JSON string (e.g. ``'["a", "b"]'``) → parsed list (invalid → ``[]``)
    * comma-separated string (e.g. ``"a, b"``) → split and trimmed tokens
    * any other unexpected type → ``[]``

    Never raises; the API contract requires ``reasons`` to be a list.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item is not None]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return []
            if isinstance(parsed, list):
                return [str(item) for item in parsed if item is not None]
            return []
        # Fallback: comma-separated string.
        return [part.strip() for part in text.split(",") if part.strip()]
    return []


def _triage_days_to_close(close_date: datetime | None) -> int | None:
    """Compute days_to_close without clamping negatives.

    Per PR B-1a spec: an opportunity that has already closed can still appear
    in closing_soon_7d as a negative number. None means no close_date at all.
    """
    if close_date is None:
        return None
    now = datetime.now(UTC).replace(tzinfo=None)
    return (close_date - now).days


def get_review_queue(
    db: Session,
    organization_id: str,
    *,
    limit: int = 8,
) -> list[TriageOpportunityItem]:
    """Return up to ``limit`` items the user has marked for review or kept.

    Filter: ``Opportunity.organization_id == org_id`` AND
            ``Opportunity.user_status IN ('review', 'kept')`` AND
            ``Opportunity.close_date >= today_start``.
    Order: ``close_date ASC NULLS LAST`` (soonest first).
    Score: joined from ``OpportunityScore`` for the given org, if any.
    """
    today_start = datetime.now(UTC).replace(tzinfo=None).replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(Opportunity, OpportunityScore, Source)
        .outerjoin(
            OpportunityScore,
            and_(
                OpportunityScore.opportunity_id == Opportunity.id,
                OpportunityScore.organization_id == organization_id,
            ),
        )
        .outerjoin(Source, Source.id == Opportunity.source_id)
        .where(
            Opportunity.organization_id == organization_id,
            Opportunity.user_status.in_(["review", "kept"]),
            Opportunity.close_date >= today_start,
        )
        .order_by(Opportunity.close_date.asc().nullslast())
        .limit(limit)
    )
    rows = list(db.execute(stmt))
    items: list[TriageOpportunityItem] = []
    for opportunity, score, source in rows:
        items.append(
            TriageOpportunityItem(
                id=opportunity.id,
                title=opportunity.title,
                country=opportunity.country,
                currency=opportunity.funding_amount_currency,
                funding_amount=opportunity.funding_amount_value,
                days_to_close=_triage_days_to_close(opportunity.close_date),
                score=score.score if score else None,
                source_key=source.key if source else None,
            )
        )
    return items


def get_closing_soon_7d(
    db: Session,
    organization_id: str,
    *,
    limit: int = 8,
) -> list[TriageOpportunityItem]:
    """Return up to ``limit`` items closing within 7 days (any user_status).

    Filter: ``Opportunity.organization_id == org_id OR
            Opportunity.organization_id IS NULL`` AND
            ``Opportunity.close_date IS NOT NULL`` AND
            ``now <= Opportunity.close_date <= now + 7 days``.
    Order: ``close_date ASC NULLS LAST``.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = now + timedelta(days=7)
    stmt = (
        select(Opportunity, OpportunityScore, Source)
        .outerjoin(
            OpportunityScore,
            and_(
                OpportunityScore.opportunity_id == Opportunity.id,
                OpportunityScore.organization_id == organization_id,
            ),
        )
        .outerjoin(Source, Source.id == Opportunity.source_id)
        .where(
            or_(
                Opportunity.organization_id == organization_id,
                Opportunity.organization_id.is_(None),
            ),
            Opportunity.close_date.is_not(None),
            Opportunity.close_date >= today_start,
            Opportunity.close_date <= cutoff,
        )
        .order_by(Opportunity.close_date.asc().nullslast())
        .limit(limit)
    )
    rows = list(db.execute(stmt))
    items: list[TriageOpportunityItem] = []
    for opportunity, score, source in rows:
        items.append(
            TriageOpportunityItem(
                id=opportunity.id,
                title=opportunity.title,
                country=opportunity.country,
                currency=opportunity.funding_amount_currency,
                funding_amount=opportunity.funding_amount_value,
                days_to_close=_triage_days_to_close(opportunity.close_date),
                score=score.score if score else None,
                source_key=source.key if source else None,
            )
        )
    return items


# ---------------------------------------------------------------------------
# PR B-1b: /dashboard/pipeline helpers
# ---------------------------------------------------------------------------


def _pipeline_days_to_close(close_date: datetime | None) -> int | None:
    """Compute days_to_close clamped to >= 0 (matches PipelineRead contract).

    Differs from ``_triage_days_to_close`` which can return negative values:
    pipeline closing_soon MUST NOT include already-closed items, so the
    contract is "today or later" only. The function still returns ``None``
    when there is no close_date at all.
    """
    if close_date is None:
        return None
    now = datetime.now(UTC).replace(tzinfo=None)
    days = (close_date - now).days
    return max(days, 0)


def get_top_scored(
    db: Session,
    organization_id: str,
    *,
    limit: int = 8,
) -> list[PipelineOpportunityItem]:
    """Return up to ``limit`` highest-scoring opportunities for the org.

    Filter: scored rows for the given org whose underlying opportunity is
    visible to the org scope. Each item carries the OpportunityScore
    ``score`` (float) and ``reasons`` (list[str], normalized via
    ``extract_score_reasons``) so the UI can explain why the score is what
    it is.

    Order: ``OpportunityScore.score DESC, OpportunityScore.calculated_at DESC``.
    """
    stmt = (
        select(Opportunity, OpportunityScore, Source)
        .join(
            OpportunityScore,
            and_(
                OpportunityScore.opportunity_id == Opportunity.id,
                OpportunityScore.organization_id == organization_id,
            ),
        )
        .outerjoin(Source, Source.id == Opportunity.source_id)
        .where(
            or_(
                Opportunity.organization_id == organization_id,
                Opportunity.organization_id.is_(None),
            )
        )
        .order_by(OpportunityScore.score.desc(), OpportunityScore.calculated_at.desc())
        .limit(limit)
    )
    items: list[PipelineOpportunityItem] = []
    for opportunity, score, source in db.execute(stmt):
        items.append(
            PipelineOpportunityItem(
                id=opportunity.id,
                title=opportunity.title,
                country=opportunity.country,
                currency=opportunity.funding_amount_currency,
                funding_amount=opportunity.funding_amount_value,
                days_to_close=_pipeline_days_to_close(opportunity.close_date),
                score=score.score,
                reasons=extract_score_reasons(score.reasons),
                source_key=source.key if source else None,
            )
        )
    return items


def get_closing_soon(
    db: Session,
    organization_id: str,
    *,
    limit: int = 8,
    days_window: int = 30,
) -> list[PipelineOpportunityItem]:
    """Return up to ``limit`` items closing within the ``days_window``.

    Filter: ``close_date IS NOT NULL`` AND
            ``(Opportunity.organization_id == org_id OR IS NULL)`` AND
            ``close_date`` falls on a day in ``[today, today + days_window]``.

    The lower bound uses day-granularity (start of today) so an opportunity
    that closes later today (close_date = now + 0 days) is included even if
    the row was written a few milliseconds before the request — the
    ``days_to_close`` field is exposed as an integer day count and 0 must
    mean "today", not "in the past".

    Order: ``close_date ASC NULLS LAST`` (soonest first; NULLs are already
    filtered out by the ``IS NOT NULL`` predicate).
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # Upper bound is exclusive of the next day: an item closing any time
    # during the Nth day from today (where N = days_window) is included,
    # but not anything on the (N+1)th day. This matches the contract
    # ``0 <= days_to_close <= days_window`` under day-truncated math.
    cutoff_exclusive = today_start + timedelta(days=days_window + 1)
    stmt = (
        select(Opportunity, OpportunityScore, Source)
        .outerjoin(
            OpportunityScore,
            and_(
                OpportunityScore.opportunity_id == Opportunity.id,
                OpportunityScore.organization_id == organization_id,
            ),
        )
        .outerjoin(Source, Source.id == Opportunity.source_id)
        .where(
            or_(
                Opportunity.organization_id == organization_id,
                Opportunity.organization_id.is_(None),
            ),
            Opportunity.close_date.is_not(None),
            Opportunity.close_date >= today_start,
            Opportunity.close_date < cutoff_exclusive,
        )
        .order_by(Opportunity.close_date.asc().nullslast())
        .limit(limit)
    )
    items: list[PipelineOpportunityItem] = []
    for opportunity, score, source in db.execute(stmt):
        items.append(
            PipelineOpportunityItem(
                id=opportunity.id,
                title=opportunity.title,
                country=opportunity.country,
                currency=opportunity.funding_amount_currency,
                funding_amount=opportunity.funding_amount_value,
                days_to_close=_pipeline_days_to_close(opportunity.close_date),
                score=score.score if score else None,
                reasons=[],
                source_key=source.key if source else None,
            )
        )
    return items


# ---------------------------------------------------------------------------
# PR B-1c: /dashboard/health helpers
# ---------------------------------------------------------------------------


# Local mirror of STATUS_LABELS in app.api.v1.dashboard — kept here so the
# service layer does not depend on the route module. (Mirrored, not imported,
# to avoid the circular import risk that route→service→route would create.)
_STATUS_LABELS = {
    "open": "Abiertas",
    "closing_soon": "Cierran pronto",
    "closed": "Cerradas",
    "unknown": "Sin fecha",
}


def get_health_kpis(db: Session, organization_id: str) -> HealthKpis:
    """Return the 4 KPI counts that drive the Health zone summary.

    * total: every opportunity visible to the org scope.
    * open: opportunities with status='open'.
    * closing_soon: opportunities with status='closing_soon'.
    * high_match: distinct opportunities with an OpportunityScore row
      marked priority='high' for the current org.
    """
    opportunity_scope = or_(Opportunity.organization_id == organization_id, Opportunity.organization_id.is_(None))
    total = count_query(db, build_opportunity_query(organization_id))
    open_total = count_query(db, build_opportunity_query(organization_id, status="open"))
    closing_soon_total = count_query(db, build_opportunity_query(organization_id, status="closing_soon"))
    high_match = (
        db.scalar(
            select(func.count(func.distinct(OpportunityScore.opportunity_id)))
            .select_from(OpportunityScore)
            .join(Opportunity, Opportunity.id == OpportunityScore.opportunity_id)
            .where(
                OpportunityScore.organization_id == organization_id,
                OpportunityScore.priority == "high",
                opportunity_scope,
            )
        )
        or 0
    )
    return HealthKpis(
        total=total,
        open=open_total,
        closing_soon=closing_soon_total,
        high_match=high_match,
    )


def get_status_breakdown(db: Session, organization_id: str) -> list[DashboardBreakdownItem]:
    """Group opportunities by status; return ``[{name, total}, ...]`` sorted desc.

    The same noise filters the legacy /summary used (no @ in title, no
    "http*" prefix) so the chart counts match what the consultant was
    already used to seeing.
    """
    opportunity_scope = or_(Opportunity.organization_id == organization_id, Opportunity.organization_id.is_(None))
    rows = db.execute(
        select(Opportunity.status, func.count())
        .where(opportunity_scope)
        .where(~Opportunity.title.ilike("%@%"))
        .where(~Opportunity.title.ilike("http%"))
        .group_by(Opportunity.status)
    )
    items = [
        DashboardBreakdownItem(name=_STATUS_LABELS.get(status, status), total=total)
        for status, total in rows
        if total > 0
    ]
    items.sort(key=lambda item: item.total, reverse=True)
    return items


def get_country_breakdown(db: Session, organization_id: str) -> list[DashboardBreakdownItem]:
    """Top-8 country counts; rows with empty country bucket under "Sin dato"."""
    opportunity_scope = or_(Opportunity.organization_id == organization_id, Opportunity.organization_id.is_(None))
    rows = db.execute(
        select(Opportunity.country, func.count())
        .where(opportunity_scope)
        .where(~Opportunity.title.ilike("%@%"))
        .where(~Opportunity.title.ilike("http%"))
        .group_by(Opportunity.country)
        .order_by(func.count().desc())
        .limit(8)
    )
    return [
        DashboardBreakdownItem(name=country or "Sin dato", total=total)
        for country, total in rows
        if total > 0
    ]


def get_data_coverage(db: Session, organization_id: str) -> DashboardDataCoverage:
    """Build the data-coverage strip; ``embeddings_coverage`` is now nullable.

    The embeddings field is ``None`` (not 0.0) when there are zero
    opportunities so a fresh org does not look "broken" — the frontend
    renders "Sin datos aún" for the None case. When opportunities exist
    but none have embeddings, the value is the real zero (``0.0``).
    """
    opportunity_scope = or_(Opportunity.organization_id == organization_id, Opportunity.organization_id.is_(None))
    with_summary = (
        db.scalar(
            select(func.count())
            .select_from(Opportunity)
            .where(opportunity_scope, Opportunity.summary != "", Opportunity.summary.is_not(None))
        )
        or 0
    )
    with_amount = (
        db.scalar(
            select(func.count())
            .select_from(Opportunity)
            .where(
                opportunity_scope,
                or_(Opportunity.funding_amount_value.is_not(None), Opportunity.funding_amount_raw.is_not(None)),
            )
        )
        or 0
    )
    with_close_date = (
        db.scalar(
            select(func.count()).select_from(Opportunity).where(opportunity_scope, Opportunity.close_date.is_not(None))
        )
        or 0
    )
    with_source = (
        db.scalar(
            select(func.count()).select_from(Opportunity).where(opportunity_scope, Opportunity.source_id.is_not(None))
        )
        or 0
    )
    total_opportunities = count_query(db, build_opportunity_query(organization_id))
    embeddings_total = (
        db.scalar(
            select(func.count())
            .select_from(OpportunityEmbedding)
            .join(Opportunity, Opportunity.id == OpportunityEmbedding.opportunity_id)
            .where(opportunity_scope)
        )
        or 0
    )
    embeddings_coverage: float | None = (
        round((embeddings_total / total_opportunities) * 100, 1) if total_opportunities else None
    )
    return DashboardDataCoverage(
        with_summary=with_summary,
        with_amount=with_amount,
        with_close_date=with_close_date,
        with_source=with_source,
        embeddings_coverage=embeddings_coverage,
    )


def get_sources_health(db: Session, organization_id: str) -> list[SourceHealthRead]:
    """Build a full ``SourceHealthRead`` entry for every source visible to the org.

    The per-source health is computed by the same helper that backs
    ``GET /sources/health``; we import it lazily to avoid the route →
    service → route circular dependency.
    """
    from app.api.v1.sources import _source_health  # lazy: avoid circular import

    source_scope = or_(Source.organization_id == organization_id, Source.organization_id.is_(None))
    sources = list(db.scalars(select(Source).where(source_scope)))
    return [_source_health(db, source) for source in sources]


def get_source_health_summaries(
    db: Session, organization_id: str
) -> tuple[int, int, list[DashboardSourceAlert]]:
    """Return (degraded_count, failing_count, top-5 alerts) for the org's sources.

    Mirrors the legacy /summary's source-health counts. The alerts list
    is capped at 5 entries per the original contract so the e2e and any
    client still consuming the merged summary see the same shape.
    """
    from app.api.v1.admin import _source_health_status  # lazy: avoid circular import

    source_scope = or_(Source.organization_id == organization_id, Source.organization_id.is_(None))
    sources = list(db.scalars(select(Source).where(source_scope)))

    # Batch-load the latest 10 SourceRun per source (single query instead of N+1)
    if sources:
        source_ids = [s.id for s in sources]
        all_runs = list(
            db.scalars(
                select(SourceRun)
                .where(SourceRun.source_id.in_(source_ids))
                .order_by(SourceRun.source_id, SourceRun.created_at.desc())
            )
        )
        runs_by_source: dict[str, list[SourceRun]] = {}
        for run in all_runs:
            bucket = runs_by_source.get(run.source_id)
            if bucket is None:
                runs_by_source[run.source_id] = [run]
            elif len(bucket) < 10:
                bucket.append(run)
    else:
        runs_by_source = {}

    degraded = 0
    failing = 0
    alerts: list[DashboardSourceAlert] = []
    for source in sources:
        health = _source_health_status(db, source, runs_by_source.get(source.id, []))
        if health == "degraded":
            degraded += 1
            if len(alerts) < 5:
                alerts.append(DashboardSourceAlert(source_id=source.id, name=source.name, status="degraded"))
        elif health == "failing":
            failing += 1
            if len(alerts) < 5:
                alerts.append(DashboardSourceAlert(source_id=source.id, name=source.name, status="failing"))
    return degraded, failing, alerts


# ── Analytics helpers (PR analytics-dashboard) ───────────────────────────


def get_score_distribution(db: Session, organization_id: str) -> list[DashboardBreakdownItem]:
    """Group opportunities by their score range: 0-25, 25-50, 50-75, 75-100."""
    scope = or_(
        Opportunity.organization_id == organization_id,
        Opportunity.organization_id.is_(None),
    )
    buckets = {"0-25": 0, "25-50": 0, "50-75": 0, "75-100": 0}
    rows = (
        db.execute(
            select(OpportunityScore.score)
            .join(Opportunity, OpportunityScore.opportunity_id == Opportunity.id)
            .where(scope, OpportunityScore.organization_id == organization_id)
        )
        .scalars()
        .all()
    )
    for score in rows:
        if score is None:
            continue
        if score < 25:
            buckets["0-25"] += 1
        elif score < 50:
            buckets["25-50"] += 1
        elif score < 75:
            buckets["50-75"] += 1
        else:
            buckets["75-100"] += 1
    return [
        DashboardBreakdownItem(name=k, total=v)
        for k, v in buckets.items()
        if v > 0
    ]


def _backfill_close_date_text(opp: Opportunity) -> str:
    """Combine all text fields for close_date regex extraction."""
    return " ".join(part for part in [opp.title, opp.summary, opp.description, opp.raw_text] if part)


def backfill_close_dates(db: Session, organization_id: str, *, limit: int = 500) -> dict[str, int]:
    """Extract ``close_date`` from existing text for opportunities that have
    ``close_date IS NULL``. Uses the same regex-based ``extract_close_date``
    function used during scraping (no AI calls).
    """
    from app.connectors.common import extract_close_date

    scope = or_(
        Opportunity.organization_id == organization_id,
        Opportunity.organization_id.is_(None),
    )
    stmt = (
        select(Opportunity)
        .where(scope, Opportunity.close_date.is_(None))
        .limit(limit)
    )
    opportunities = list(db.scalars(stmt))
    updated = 0
    for opp in opportunities:
        text = _backfill_close_date_text(opp)
        parsed = extract_close_date(text)
        if parsed:
            opp.close_date = parsed
            opp.status = inferred_opportunity_status(
                parsed,
                " ".join([opp.summary or "", opp.raw_text or ""]),
            )
            opp.updated_at = datetime.now(UTC).replace(tzinfo=None)
            updated += 1
    db.commit()
    return {"total": len(opportunities), "updated": updated}


def backfill_funding_amounts(db: Session, organization_id: str, *, limit: int = 500) -> dict[str, int]:
    """Parse ``funding_amount_raw`` into ``funding_amount_value`` + ``funding_amount_currency``
    for existing opportunities that have raw text but no parsed value yet.
    Uses the local regex parser only — no AI calls.
    """
    scope = or_(
        Opportunity.organization_id == organization_id,
        Opportunity.organization_id.is_(None),
    )
    stmt = (
        select(Opportunity)
        .where(
            scope,
            Opportunity.funding_amount_raw.isnot(None),
            Opportunity.funding_amount_value.is_(None),
        )
        .limit(limit)
    )
    opportunities = list(db.scalars(stmt))
    updated = 0
    for opp in opportunities:
        parsed_value, parsed_currency = _parse_funding_amount(opp.funding_amount_raw)
        if parsed_value is not None:
            opp.funding_amount_value = parsed_value
            opp.funding_amount_currency = parsed_currency
            updated += 1
    db.commit()
    return {"total": len(opportunities), "updated": updated}


def _opportunity_combined_text(opp: Opportunity) -> str:
    """Combine all text fields of an opportunity for AI extraction."""
    return " ".join(
        part for part in [opp.title, opp.summary, opp.description, opp.raw_text]
        if part
    )


def backfill_close_dates_ai(db: Session, organization_id: str, *, limit: int = 100) -> dict[str, int]:
    """Use AI (LLM) to extract close_date for opportunities that are missing it.

    Calls ``create_ai_extraction`` on each opportunity's combined text and
    updates the record if a close_date is found. More expensive than the
    regex-based backfill but can find dates in free-form text that the
    regex patterns miss.

    Processes up to ``limit`` opportunities per call. Each AI call costs
    tokens so keep batches small (10-50 recommended).
    """
    scope = or_(
        Opportunity.organization_id == organization_id,
        Opportunity.organization_id.is_(None),
    )
    stmt = (
        select(Opportunity)
        .where(scope, Opportunity.close_date.is_(None))
        .order_by(Opportunity.updated_at.desc())
        .limit(limit)
    )
    opportunities = list(db.scalars(stmt))
    processed = 0
    updated = 0
    for opp in opportunities:
        try:
            text = _opportunity_combined_text(opp)
            if not text.strip():
                continue
            processed += 1
            extraction = create_ai_extraction(text)
            close_date = _parse_ai_close_date(extraction.get("close_date"))
            if close_date:
                opp.close_date = close_date
                opp.status = inferred_opportunity_status(
                    close_date,
                    " ".join([opp.summary or "", opp.raw_text or ""]),
                )
                opp.updated_at = datetime.now(UTC).replace(tzinfo=None)
                updated += 1
        except Exception:
            logger.warning("backfill_close_dates_ai.skip", opportunity_id=opp.id)
            continue
    db.commit()
    return {"total": len(opportunities), "processed": processed, "updated": updated}


def get_funding_ranges(db: Session, organization_id: str) -> list[DashboardBreakdownItem]:
    """Group opportunities by their funding amount range."""
    scope = or_(
        Opportunity.organization_id == organization_id,
        Opportunity.organization_id.is_(None),
    )
    buckets = {
        "<$100K": 0,
        "$100K-$500K": 0,
        "$500K-$1M": 0,
        "$1M-$5M": 0,
        ">$5M": 0,
    }
    rows = (
        db.execute(
            select(Opportunity.funding_amount_value)
            .where(scope, Opportunity.funding_amount_value.isnot(None))
        )
        .scalars()
        .all()
    )
    for amount in rows:
        if amount is None:
            continue
        if amount < 100_000:
            buckets["<$100K"] += 1
        elif amount < 500_000:
            buckets["$100K-$500K"] += 1
        elif amount < 1_000_000:
            buckets["$500K-$1M"] += 1
        elif amount < 5_000_000:
            buckets["$1M-$5M"] += 1
        else:
            buckets[">$5M"] += 1
    return [
        DashboardBreakdownItem(name=k, total=v)
        for k, v in buckets.items()
        if v > 0
    ]


def get_source_contribution(db: Session, organization_id: str) -> list[DashboardBreakdownItem]:
    """Top 10 sources by the number of opportunities they contributed."""
    scope = or_(
        Opportunity.organization_id == organization_id,
        Opportunity.organization_id.is_(None),
    )
    rows = (
        db.execute(
            select(Source.name, func.count())
            .join(Opportunity, Opportunity.source_id == Source.id)
            .where(scope)
            .group_by(Source.name)
            .order_by(func.count().desc())
            .limit(10)
        )
        .all()
    )
    return [DashboardBreakdownItem(name=name or "Unknown", total=count) for name, count in rows]


def get_opportunities_timeline(db: Session, organization_id: str) -> list[DashboardBreakdownItem]:
    """Count opportunities scraped per month (last 12 months)."""
    from datetime import datetime as dt

    scope = or_(
        Opportunity.organization_id == organization_id,
        Opportunity.organization_id.is_(None),
    )
    cutoff = dt.now(UTC).replace(tzinfo=None) - timedelta(days=365)
    rows = (
        db.execute(
            select(
                func.date_trunc("month", Opportunity.created_at).label("month"),
                func.count(),
            )
            .where(scope, Opportunity.created_at >= cutoff)
            .group_by("month")
            .order_by("month")
        )
        .all()
    )
    return [
        DashboardBreakdownItem(
            name=str(month.strftime("%Y-%m")) if month else "Unknown",
            total=count,
        )
        for month, count in rows
    ]


def get_category_distribution(db: Session, organization_id: str) -> list[DashboardBreakdownItem]:
    """Count opportunities grouped by their source's category tags.

    Source.category is a JSON array stored as a PostgreSQL JSONB column.
    Some PG versions (Supabase free tier) do not support cross-join
    lateral with jsonb_array_elements_text in SQLAlchemy. We fall back to
    fetching the raw rows and unnesting in Python.
    """
    scope = or_(
        Opportunity.organization_id == organization_id,
        Opportunity.organization_id.is_(None),
    )
    rows = (
        db.execute(
            select(Source.category)
            .join(Opportunity, Opportunity.source_id == Source.id)
            .where(scope)
        )
        .scalars()
        .all()
    )
    from collections import Counter

    # Normalize category tags from English/mixed to Spanish.
    CATEGORY_MAP: dict[str, str] = {
        "grants": "subvenciones",
        "research": "investigación",
        "innovation": "innovación",
        "development": "desarrollo",
        "education": "educación",
        "health": "salud",
        "agriculture": "agricultura",
        "environment": "medio ambiente",
        "energy": "energía",
        "technology": "tecnología",
        "infrastructure": "infraestructura",
        "social": "social",
        "culture": "cultura",
        "science": "ciencia",
        "sustainability": "sostenibilidad",
        "entrepreneurship": "emprendimiento",
        "startup": "startup",
        "cooperation": "cooperación",
        "funding": "financiamiento",
        "investment": "inversión",
        "procurement": "contratación",
        "humanitarian": "humanitario",
        "climate": "clima",
        "digital": "digital",
        "mobility": "movilidad",
        "tourism": "turismo",
        "security": "seguridad",
        "defense": "defensa",
        "space": "espacio",
        "oceans": "océanos",
        "biodiversity": "biodiversidad",
        "water": "agua",
        "food": "alimentos",
        "healthcare": "salud",
        "pharma": "farmacéutica",
        "biotech": "biotecnología",
        "nanotech": "nanotecnología",
        "robotics": "robótica",
        "blockchain": "blockchain",
        "iot": "iot",
        "big data": "big data",
        "cybersecurity": "ciberseguridad",
        "cloud": "nube",
        "quantum": "cuántica",
        "semiconductors": "semiconductores",
        "renewable": "renovable",
        "nuclear": "nuclear",
        "hydrogen": "hidrógeno",
        "carbon": "carbono",
        "circular economy": "economía circular",
        "waste": "residuos",
        "recycling": "reciclaje",
        "gender": "género",
        "inclusion": "inclusión",
        "youth": "juventud",
        "indigenous": "indígena",
        "rural": "rural",
        "urban": "urbano",
        "migration": "migración",
        "peace": "paz",
        "governance": "gobernanza",
        "transparency": "transparencia",
        "anticorruption": "anticorrupción",
        "tax": "impuestos",
        "trade": "comercio",
        "exports": "exportaciones",
        "tourism": "turismo",
        "creative industries": "industrias creativas",
        "media": "medios",
        "sports": "deportes",
        "federal funding": "fondos federales",
        "horizon europe": "horizonte europa",
        "becas": "becas",
        "convocatorias": "convocatorias",
        "formacion": "formación",
        "financiamiento": "financiamiento",
        "garantias": "garantías",
        "tic": "tic",
        "agro": "agro",
        "pyme": "pyme",
        "capital-semilla": "capital semilla",
        "industria": "industria",
        "productividad": "productividad",
        "solidaria": "economía solidaria",
        "comunitario": "comunitario",
        "estadual": "estadual",
        "filantropia": "filantropía",
        "internet": "internet",
    }
    counter: Counter[str] = Counter()
    for category_list in rows:
        if isinstance(category_list, list):
            for cat in category_list:
                if isinstance(cat, str) and cat.strip():
                    translated = CATEGORY_MAP.get(cat.strip().lower(), cat.strip().lower())
                    counter[translated] += 1
    items = counter.most_common(12)
    return [DashboardBreakdownItem(name=cat, total=count) for cat, count in items]


# ---------------------------------------------------------------------------
# GenAI features: batch summarize / batch score / weekly digest
# ---------------------------------------------------------------------------


def summarize_missing_opportunities(
    db: Session,
    organization_id: str | None,
    *,
    limit: int = 10,
) -> dict[str, int]:
    """Find opportunities without a summary and call ``summarize_text`` for each.

    Limited to ``limit`` per call to stay under the Gemini free-tier quota when
    the LLM provider is configured against ``generativelanguage.googleapis.com``.
    Returns ``{"processed": N, "summarized": M}`` where ``N`` is the number of
    candidates considered and ``M`` is the count that received a new summary.
    """
    scope = or_(
        Opportunity.organization_id == organization_id,
        Opportunity.organization_id.is_(None),
    ) if organization_id else True
    stmt = (
        select(Opportunity)
        .where(
            scope,
            or_(Opportunity.summary.is_(None), Opportunity.summary == ""),
        )
        .order_by(Opportunity.created_at.desc())
        .limit(limit)
    )
    candidates = list(db.scalars(stmt))
    summarized = 0
    for opportunity in candidates:
        source_text = (opportunity.raw_text or opportunity.description or "").strip()
        if not source_text:
            continue
        try:
            summary = summarize_text(source_text)
        except Exception:
            # Local fallback is non-throwing; remote calls may still fail. Skip
            # silently and let the next batch pick it up.
            continue
        if not summary:
            continue
        opportunity.summary = summary
        summarized += 1
    if summarized:
        db.commit()
    return {"processed": len(candidates), "summarized": summarized}


def rescore_all_opportunities(
    db: Session,
    organization_id: str,
    *,
    limit: int = 10,
) -> dict[str, int]:
    """Recalculate scores for ALL opportunities for this org, overwriting
    existing OpportunityScore rows. Uses the new multi-dimensional scorer.
    """
    organization = db.get(Organization, organization_id)
    profile = db.scalar(
        select(OrganizationProfile).where(OrganizationProfile.organization_id == organization_id)
    )
    if organization is None or profile is None:
        return {"processed": 0, "rescored": 0}

    scope = or_(
        Opportunity.organization_id == organization_id,
        Opportunity.organization_id.is_(None),
    )
    opportunities = list(db.scalars(select(Opportunity).where(scope).limit(limit)))
    processed = len(opportunities)
    rescored = 0
    for opp in opportunities:
        existing = db.scalar(
            select(OpportunityScore).where(
                OpportunityScore.opportunity_id == opp.id,
                OpportunityScore.organization_id == organization_id,
            )
        )
        if existing:
            # Reuse existing row — update in place
            score = _compute_score(opp, profile)
            existing.score = min(round(score["raw"], 1), 100)
            existing.priority = priority_for_score(existing.score)
            existing.reasons = score["reasons"]
            existing.warnings = score["warnings"]
        else:
            new_score = calculate_score(db, opp, profile)
            db.add(new_score)
        rescored += 1
    db.commit()
    return {"processed": processed, "rescored": rescored}


def score_unscored_opportunities(
    db: Session,
    organization_id: str,
    *,
    limit: int = 10,
) -> dict[str, int]:
    """Score opportunities that have no OpportunityScore row for this org yet.

    Returns ``{"processed": N, "scored": M}`` where ``N`` is the number of
    candidates considered and ``M`` is the count that received a new score.
    """
    # Default profile fallback: if the org has no profile yet, build a minimal
    # in-memory profile so calculate_score has something to compare against.
    organization = db.get(Organization, organization_id)
    profile = db.scalar(
        select(OrganizationProfile).where(OrganizationProfile.organization_id == organization_id)
    )
    if organization is None:
        return {"processed": 0, "scored": 0}

    if profile is None:
        profile = OrganizationProfile(
            organization_id=organization_id,
            country=organization.country or "Colombia",
        )
        db.add(profile)
        db.flush()

    # Use LEFT OUTER JOIN instead of NOT IN (subquery) — sqlite's NOT IN on
    # an empty subquery produces zero rows because NULL is the default, so
    # outer-join + IS NULL is the portable pattern.
    scope = or_(
        Opportunity.organization_id == organization_id,
        Opportunity.organization_id.is_(None),
    )
    stmt = (
        select(Opportunity)
        .outerjoin(
            OpportunityScore,
            and_(
                OpportunityScore.opportunity_id == Opportunity.id,
                OpportunityScore.organization_id == organization_id,
            ),
        )
        .where(scope, OpportunityScore.id.is_(None))
        .order_by(Opportunity.created_at.desc())
        .limit(limit)
    )
    candidates = list(db.scalars(stmt))
    scored = 0
    for opportunity in candidates:
        try:
            calculate_score(db, opportunity, profile)
            scored += 1
        except Exception:
            db.rollback()
            continue
    if scored:
        db.commit()
    return {"processed": len(candidates), "scored": scored}


def build_weekly_digest_html(
    *,
    organization: Organization,
    opportunities: list[Opportunity],
) -> str:
    """Render a simple HTML email for the weekly digest.

    Top 5 opportunities by recency. Intentionally minimal — this is the MVP
    digest, not a magazine layout. The frontend has the real design system.
    """
    rows: list[str] = []
    for item in opportunities[:5]:
        title = escape(item.title or "Convocatoria sin título")
        entity = escape(item.entity or "Sin entidad")
        country = escape(item.country or "")
        summary = escape((item.summary or item.description or "")[:280])
        url = item.official_url or item.application_url or "#"
        rows.append(
            f"<tr><td style='padding:12px 0;border-bottom:1px solid #e2e8f0;'>"
            f"<a href='{escape(url)}' style='font-size:15px;font-weight:600;color:#0f172a;text-decoration:none;'>{title}</a>"
            f"<p style='margin:4px 0 0;font-size:12px;color:#64748b;'>{entity} · {country}</p>"
            f"<p style='margin:6px 0 0;font-size:13px;color:#334155;line-height:1.5;'>{summary}</p>"
            f"</td></tr>"
        )
    body_rows = "".join(rows) or (
        "<tr><td style='padding:16px 0;color:#64748b;'>No se detectaron oportunidades nuevas esta semana.</td></tr>"
    )
    return (
        "<html><body style='font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f8fafc;padding:24px;'>"
        f"<div style='max-width:640px;margin:0 auto;background:#ffffff;padding:24px;border-radius:12px;border:1px solid #e2e8f0;'>"
        f"<h1 style='margin:0 0 4px;font-size:20px;color:#0f172a;'>Resumen semanal · {escape(organization.name)}</h1>"
        f"<p style='margin:0 0 16px;font-size:13px;color:#64748b;'>"
        f"Top {min(len(opportunities), 5)} convocatorias detectadas en los últimos 7 días."
        f"</p>"
        f"<table style='width:100%;border-collapse:collapse;'>{body_rows}</table>"
        f"<p style='margin:16px 0 0;font-size:12px;color:#94a3b8;'>"
        f"ConvocaRadar IA · Generado automáticamente"
        f"</p></div></body></html>"
    )


def send_weekly_digest(db: Session, organization_id: str) -> bool:
    """Send a weekly digest email to the first admin user of the org.

    Returns True if the email was handed off to the SMTP transport (or
    recorded as a dev dry-run), False on hard failure. The digest is
    limited to the most recent 7 days of opportunities visible to the org.
    """
    from app.core.email import send_email
    from app.models import User

    organization = db.get(Organization, organization_id)
    if organization is None:
        return False
    recipient = db.scalar(
        select(User.email)
        .where(User.organization_id == organization_id, User.role == Role.admin.value)
        .order_by(User.created_at.asc())
        .limit(1)
    )
    if not recipient:
        return False

    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=7)
    scope = or_(
        Opportunity.organization_id == organization_id,
        Opportunity.organization_id.is_(None),
    )
    opportunities = list(
        db.scalars(
            select(Opportunity)
            .where(scope, Opportunity.created_at >= cutoff)
            .order_by(Opportunity.created_at.desc())
            .limit(5)
        )
    )
    html_body = build_weekly_digest_html(organization=organization, opportunities=opportunities)
    subject = f"ConvocaRadar · Resumen semanal ({len(opportunities)} nuevas)"
    try:
        send_email(
            recipient=recipient,
            subject=subject,
            message=html_body,
        )
    except Exception:
        return False
    return True
