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
from app.services.dashboard import (  # noqa: F401
    _STATUS_LABELS,
    extract_score_reasons,
)


def connector_for(source_key: str, base_url: str | None = None, source_type: str | None = None, *, entity_name: str | None = None, default_country: str | None = None, default_categories: list[str] | None = None, connector_config: dict | None = None):
    from app.connectors.factory import connector_for as worker_connector_for

    return worker_connector_for(source_key, base_url, source_type, entity_name=entity_name, default_country=default_country, default_categories=default_categories, connector_config=connector_config)


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
    """Thin sync wrapper — delegates to app.scraper.runner.run_source_inline.

    FastAPI sync endpoints run in a thread pool.  ``asyncio.run()`` in a
    thread can deadlock with the parent event loop on some platforms, so
    we use an explicit fresh loop (same pattern as the original).
    """
    from app.scraper.runner import run_source_inline

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(run_source_inline(db, source, organization_id))
    finally:
        loop.close()


def create_heuristic_extraction(text: str) -> dict[str, object]:
    return build_local_extraction(text)


async def create_ai_extraction(text: str) -> dict[str, object]:
    extraction = await extract_opportunity_structured(text)
    return extraction.data


def summarize_text(text: str) -> str:
    return summarize_opportunity_text(text)


def count_query(db: Session, stmt: Select[tuple[Opportunity]]) -> int:
    return db.scalar(select(func.count()).select_from(stmt.subquery())) or 0


# ---------------------------------------------------------------------------
# PR B-1c: /dashboard/health helpers
# ---------------------------------------------------------------------------


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


async def backfill_close_dates_ai(db: Session, organization_id: str, *, limit: int = 100) -> dict[str, int]:
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
            extraction = await create_ai_extraction(text)
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


async def backfill_funding_amounts_ai(db: Session, organization_id: str, *, limit: int = 100) -> dict[str, int]:
    """Use AI (LLM) to extract ``funding_amount_raw`` for opportunities missing it.

    Calls ``create_ai_extraction`` on each opportunity's combined text and
    updates ``funding_amount_raw`` + ``funding_amount_value`` + 
    ``funding_amount_currency`` if parsed. Regex is tried first; AI is the
    fallback. Batch small (10-50) due to token cost.
    """
    scope = or_(
        Opportunity.organization_id == organization_id,
        Opportunity.organization_id.is_(None),
    )
    stmt = (
        select(Opportunity)
        .where(scope, Opportunity.funding_amount_raw.is_(None))
        .order_by(Opportunity.confidence_score.desc())
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
            extraction = await create_ai_extraction(text)
            raw = extraction.get("funding_amount_raw")
            if raw and isinstance(raw, str) and raw.strip():
                opp.funding_amount_raw = raw.strip()
                parsed_value, parsed_currency = _parse_funding_amount(raw)
                if parsed_value is not None:
                    opp.funding_amount_value = parsed_value
                    opp.funding_amount_currency = parsed_currency
                opp.updated_at = datetime.now(UTC).replace(tzinfo=None)
                updated += 1
        except Exception:
            logger.warning("backfill_funding_amounts_ai.skip", opportunity_id=opp.id)
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

    # Prefer configured default recipient, fall back to first admin user
    settings = get_settings()
    recipient = settings.alert_default_recipient
    if not recipient:
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
