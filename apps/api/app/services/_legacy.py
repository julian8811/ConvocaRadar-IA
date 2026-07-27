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

# ── Re-imports from opportunity.py ────────────────────────────────────────────
# These let modules still importing from _legacy (analytics.py, genai.py,
# dashboard.py) continue to work until they're updated to import directly.
from app.services.opportunity import (  # noqa: F401
    _combined_text,
    _parse_ai_close_date,
    _parse_funding_amount,
    _update_opportunity,
    _update_and_score,
    count_query,
    create_ai_extraction,
    create_heuristic_extraction,
    create_opportunity,
    enrich_opportunity_payload,
    inferred_opportunity_status,
    opportunity_status,
    reanalyze_opportunity,
    summarize_text,
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


