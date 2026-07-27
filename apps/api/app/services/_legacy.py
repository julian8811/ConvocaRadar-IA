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
from app.core.http_client import sync_http_client
from app.core.ai import (
    build_embedding,
    build_embedding_sync,
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

# ── Re-imports from specialized modules ─────────────────────────────────────
# These let remaining functions in this module continue calling the extracted
# functions through the _legacy module's namespace.
from app.services.validation import (  # noqa: F401
    is_noise_payload,
    slugify,
    url_is_reachable,
)
from app.services.dedup import (  # noqa: F401
    _organization_opportunity_scope,
    candidate_external_id,
    find_duplicate_opportunity,
)
from app.services.scoring import (  # noqa: F401
    _compute_score,
    calculate_score,
    priority_for_score,
)
from app.services.search import build_opportunity_query  # noqa: F401
from app.services.embeddings import (  # noqa: F401
    opportunity_reanalysis_text,
    upsert_opportunity_embedding,
)

# ── Re-imports from connectors.py ────────────────────────────────────────────
# These let remaining functions in this module continue calling the connector
# functions through the _legacy module's namespace (for functions that haven't
# been updated to import from the new module yet).
from app.services.connectors import (  # noqa: F401
    connector_for,
    is_slow_scrape_source,
    source_due_for_scraping,
)


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
    Returns ``(None, None)`` when no pattern matches or when the
    extracted value looks like a non-funding number (too small, no
    explicit currency indicator).
    """
    if not funding_raw:
        return None, None

    text = funding_raw.strip()
    upper_text = text.upper()

    # Guard: require at least one digit for any amount parsing
    if not re.search(r"\d", text):
        return None, None

    # Detect currency from prefix/suffix — require explicit currency
    # marker to avoid picking up random numbers from body text.
    currency = None
    currency_map: list[tuple[str | None, list[str]]] = [
        ("COP", ["COP", "COL$"]),
        ("EUR", ["EUR", "€"]),
        ("GBP", ["GBP", "£"]),
        ("BRL", ["BRL", "R$"]),
        ("MXN", ["MXN", "MX$"]),
        ("USD", ["USD", "US$"]),
    ]
    for code, symbols in currency_map:
        if any(sym in upper_text for sym in symbols):
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

    # Handle million/k suffixes — but only when the suffix is attached
    # to the number, not to arbitrary body text.
    million_suffix = re.search(r"(?:million|MM|millón|millones)\b", text, re.IGNORECASE)
    k_suffix = re.search(r"\b[kK]\b", text)
    ends_with_m = bool(re.search(r"\d+M(?:$|\s)", text))

    if million_suffix or ends_with_m:
        value *= 1_000_000
    elif k_suffix and value < 1_000_000:
        value *= 1_000

    # ── Quality gates ──────────────────────────────────────────────
    # Reject values that look like non-funding numbers from body text.

    # If no explicit currency was detected, require a larger number
    # (>= 1000) to avoid picking up page numbers, years, or counts.
    if currency is None:
        return None, None

    # If currency is a strong code (COP, EUR, GBP, BRL, MXN) accept it.
    # For USD detected via bare "$" (weak signal), require >= 500.
    if currency == "USD" and not re.search(r"(?:USD|US\$)", upper_text):
        # USD detected only by bare "$" — require a meaningful amount
        if value < 500:
            return None, None

    # Cap absurdly large values (> 1 trillion) — likely parsing error
    if value > 1_000_000_000_000:
        return None, None

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


async def enrich_opportunity_payload(data: OpportunityCreate) -> OpportunityCreate:
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
    extraction = await create_ai_extraction(raw_text)
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
    if merged["close_date"] and merged.get("risk_flags"):
        merged["risk_flags"] = [
            flag
            for flag in merged["risk_flags"]
            if "no se detectó una fecha de cierre" not in str(flag).lower()
        ]
    # ── Post-processing: country inference + title cleanup ──────────────
    from app.connectors.common import clean_opportunity_title, infer_country_from_entity
    merged["title"] = clean_opportunity_title(merged.get("title"))
    if not merged.get("country") or merged["country"] in ("Por validar", "Sin dato", ""):
        inferred = infer_country_from_entity(
            merged.get("entity"), merged.get("official_url"),
        )
        if inferred and inferred != "Por validar":
            merged["country"] = inferred
    return OpportunityCreate(**merged)


async def reanalyze_opportunity(db: Session, opportunity: Opportunity, *, force: bool = False) -> Opportunity:
    text = opportunity_reanalysis_text(db, opportunity)
    if not text.strip():
        return opportunity
    extraction = await create_ai_extraction(text)
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
        await upsert_opportunity_embedding(db, opportunity)
    return opportunity


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




def _update_opportunity(
    opportunity: Opportunity,
    data: OpportunityCreate,
    normalized_title: str,
) -> None:
    """Apply scraped data to an existing opportunity record."""
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
        data.close_date, " ".join([data.summary, data.raw_text]),
    )


async def _update_and_score(
    db: Session,
    opportunity: Opportunity,
    data: OpportunityCreate,
    normalized_title: str,
    score_org_id: str | None,
) -> Opportunity:
    """Update opportunity, recalculate embedding + score."""
    _update_opportunity(opportunity, data, normalized_title)
    actual_org_id = opportunity.organization_id or score_org_id
    await upsert_opportunity_embedding(db, opportunity)
    if actual_org_id:
        profile = db.scalar(select(OrganizationProfile).where(OrganizationProfile.organization_id == actual_org_id))
        if profile:
            calculate_score(db, opportunity, profile)
    return opportunity


async def create_opportunity(db: Session, data: OpportunityCreate, organization_id: str | None = None) -> Opportunity:
    data = await enrich_opportunity_payload(data)
    normalized_title = data.title.strip()
    if is_noise_payload(normalized_title, data.summary, data.raw_text):
        raise ValueError("Opportunity title looks like scraping noise")
    slug = slugify(f"{normalized_title}-{data.entity}")
    score_org_id = organization_id
    if data.official_url and not url_is_reachable(data.official_url):
        data = data.model_copy(update={"official_url": None})
    if data.application_url and not url_is_reachable(data.application_url):
        data = data.model_copy(update={"application_url": None})

    # ── Dedup checks (ordered by specificity) ─────────────────────────────
    if data.external_id and data.source_id:
        existing = db.scalar(
            select(Opportunity).where(
                Opportunity.source_id == data.source_id,
                Opportunity.external_id == data.external_id,
                or_(Opportunity.organization_id == organization_id, Opportunity.organization_id.is_(None)),
            )
        )
        if existing:
            return await _update_and_score(db, existing, data, normalized_title, score_org_id)

    if data.external_id and data.external_id.startswith("dedup-"):
        existing = db.scalar(
            select(Opportunity).where(
                Opportunity.external_id == data.external_id,
                _organization_opportunity_scope(organization_id),
            ).order_by(Opportunity.first_seen_at.asc())
        )
        if existing:
            return await _update_and_score(db, existing, data, normalized_title, score_org_id)

    duplicate = find_duplicate_opportunity(db, data, organization_id)
    if duplicate:
        return await _update_and_score(db, duplicate, data, normalized_title, score_org_id)

    if data.source_id and data.official_url:
        existing = db.scalar(
            select(Opportunity).where(
                Opportunity.source_id == data.source_id,
                Opportunity.official_url == data.official_url,
                or_(Opportunity.organization_id == organization_id, Opportunity.organization_id.is_(None)),
            )
        )
        if existing:
            return await _update_and_score(db, existing, data, normalized_title, score_org_id)

    existing = db.scalar(
        select(Opportunity).where(
            Opportunity.slug == slug,
            Opportunity.entity == data.entity,
            Opportunity.close_date == data.close_date,
        )
    )
    if existing:
        _update_opportunity(existing, data, normalized_title)
        await upsert_opportunity_embedding(db, existing)
        return existing

    # ── Create new opportunity ────────────────────────────────────────────
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
    await upsert_opportunity_embedding(db, opportunity)
    if score_org_id:
        profile = db.scalar(select(OrganizationProfile).where(OrganizationProfile.organization_id == score_org_id))
        if profile:
            calculate_score(db, opportunity, profile)
    return opportunity




def create_heuristic_extraction(text: str) -> dict[str, object]:
    return build_local_extraction(text)


async def create_ai_extraction(text: str) -> dict[str, object]:
    extraction = await extract_opportunity_structured(text)
    return extraction.data


def summarize_text(text: str) -> str:
    return summarize_opportunity_text(text)


def count_query(db: Session, stmt: Select[tuple[Opportunity]]) -> int:
    return db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
