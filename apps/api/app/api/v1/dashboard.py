from datetime import UTC, datetime
import time

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_organization, get_current_user
from app.api.v1.admin import _source_health_status
from app.db.session import get_db
from app.models import Opportunity, OpportunityEmbedding, OpportunityScore, Organization, OrganizationProfile, Source, User
from app.schemas import (
    DashboardBreakdownItem,
    DashboardDataCoverage,
    DashboardOpportunityItem,
    DashboardProfileSummary,
    DashboardSourceAlert,
    DashboardSummaryRead,
    HealthKpis,
    HealthRead,
    PipelineRead,
    TriageRead,
)
from app.services import (
    build_opportunity_query,
    count_query,
    get_category_distribution,
    get_closing_soon,
    get_closing_soon_7d,
    get_country_breakdown,
    get_data_coverage,
    get_funding_ranges,
    get_health_kpis,
    get_opportunities_timeline,
    get_review_queue,
    get_score_distribution,
    get_source_contribution,
    get_source_health_summaries,
    get_sources_health,
    get_status_breakdown,
    get_top_scored,
    is_noise_payload,
)

router = APIRouter()

# ── Simple in-memory cache for /dashboard/health ──────────────────────
# The background source sweep (123 sources on free tier) saturates the
# DB and makes the health endpoint take >12s, which kills the frontend's
# AbortController. A 60s TTL module-level dict serves as a lightweight
# cache so subsequent calls within the window return instantly.
_health_cache: dict[str, tuple[float, HealthRead | None]] = {}

PROFILE_CHECKS: list[tuple[str, str]] = [
    ("description", "Descripción institucional"),
    ("areas_of_interest", "Áreas de interés"),
    ("funding_types", "Tipos de financiación"),
    ("organization_type", "Tipo de organización"),
    ("preferred_currencies", "Monedas preferidas"),
]

STATUS_LABELS = {
    "open": "Abiertas",
    "closing_soon": "Cierran pronto",
    "closed": "Cerradas",
    "unknown": "Sin fecha",
}


def _profile_summary(profile: OrganizationProfile | None) -> DashboardProfileSummary:
    if profile is None:
        return DashboardProfileSummary(completeness=0.0, missing_fields=[label for _, label in PROFILE_CHECKS])

    filled = 0
    missing: list[str] = []
    for field, label in PROFILE_CHECKS:
        value = getattr(profile, field)
        has_value = bool(value.strip()) if isinstance(value, str) else bool(value)
        if field == "organization_type":
            has_value = profile.organization_type not in {"", "other"}
        if has_value:
            filled += 1
        else:
            missing.append(label)

    completeness = round((filled / len(PROFILE_CHECKS)) * 100, 1) if PROFILE_CHECKS else 0.0
    return DashboardProfileSummary(completeness=completeness, missing_fields=missing)


def _days_to_close(close_date: datetime | None) -> int | None:
    if close_date is None:
        return None
    return max((close_date - datetime.now(UTC).replace(tzinfo=None)).days, 0)


def _to_opportunity_item(opportunity: Opportunity, score: OpportunityScore | None = None) -> DashboardOpportunityItem:
    return DashboardOpportunityItem(
        id=opportunity.id,
        title=opportunity.title,
        entity=opportunity.entity,
        country=opportunity.country,
        status=opportunity.status,
        close_date=opportunity.close_date,
        funding_amount_raw=opportunity.funding_amount_raw,
        funding_amount_value=opportunity.funding_amount_value,
        funding_amount_currency=opportunity.funding_amount_currency,
        score=score.score if score else None,
        priority=score.priority if score else None,
        days_to_close=_days_to_close(opportunity.close_date),
    )


def _visible_opportunity(opportunity: Opportunity) -> bool:
    return not is_noise_payload(opportunity.title, opportunity.summary, opportunity.raw_text)


@router.get("/dashboard/summary", response_model=DashboardSummaryRead)
def get_dashboard_summary(
    response: Response,
    organization: Organization = Depends(get_current_organization),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DashboardSummaryRead:
    """PR B-1c deprecated alias for the legacy /dashboard/summary endpoint.

    The /dashboard/{triage,pipeline,health} endpoints are the new canonical
    sources of truth. This alias merges the same data into the original
    ``DashboardSummaryRead`` shape so the existing e2e spec and any external
    clients keep working. Removal is targeted for the release after
    ``Sat, 01 Aug 2026`` (RFC 8594 Sunset).

    Deprecation headers are emitted on every response:

    * ``Deprecation: true`` (RFC 9745)
    * ``Sunset: Sat, 01 Aug 2026 00:00:00 GMT`` (RFC 8594)
    * ``Link: </api/v1/dashboard/triage|pipeline|health>; rel="successor-version"``

    The ``embeddings_coverage`` field is now ``float | None`` (``None`` when
    the org has zero opportunities) so a fresh org no longer reads as
    "0% embeddings — broken".
    """
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "Sat, 01 Aug 2026 00:00:00 GMT"
    response.headers["Link"] = (
        '</api/v1/dashboard/triage>; rel="successor-version", '
        '</api/v1/dashboard/pipeline>; rel="successor-version", '
        '</api/v1/dashboard/health>; rel="successor-version"'
    )

    opportunity_scope = or_(
        Opportunity.organization_id == organization.id, Opportunity.organization_id.is_(None)
    )
    source_scope = or_(Source.organization_id == organization.id, Source.organization_id.is_(None))

    # ---- Reusable: kpis, breakdowns, data_coverage, source health ----
    kpis = get_health_kpis(db, organization.id)
    status_breakdown = get_status_breakdown(db, organization.id)
    country_breakdown = get_country_breakdown(db, organization.id)
    data_coverage = get_data_coverage(db, organization.id)
    degraded_sources, failing_sources, source_alerts = get_source_health_summaries(db, organization.id)

    # ---- Alias-specific: top_scored + closing_soon keep the legacy
    # ``DashboardOpportunityItem`` shape (entity, country, status,
    # close_date, funding_amount_value/raw/currency) so any external client
    # still consuming the merged summary continues to receive a compatible
    # response. The new /dashboard/pipeline endpoint exposes a slimmer
    # ``PipelineOpportunityItem`` (id, title, country, currency, funding,
    # days_to_close, score, reasons, source_key).
    score_rows = list(
        db.execute(
            select(Opportunity, OpportunityScore)
            .join(OpportunityScore, OpportunityScore.opportunity_id == Opportunity.id)
            .where(
                OpportunityScore.organization_id == organization.id,
                opportunity_scope,
            )
            .order_by(OpportunityScore.score.desc(), OpportunityScore.calculated_at.desc())
            .limit(40)
        )
    )
    top_scored: list[DashboardOpportunityItem] = []
    seen_scores: set[str] = set()
    for opportunity, score in score_rows:
        if opportunity.id in seen_scores or not _visible_opportunity(opportunity):
            continue
        seen_scores.add(opportunity.id)
        top_scored.append(_to_opportunity_item(opportunity, score))
        if len(top_scored) >= 8:
            break

    closing_soon = [
        _to_opportunity_item(item)
        for item in db.scalars(build_opportunity_query(organization.id, status="closing_soon").limit(8))
        if _visible_opportunity(item)
    ]

    profile = db.scalar(select(OrganizationProfile).where(OrganizationProfile.organization_id == organization.id))

    return DashboardSummaryRead(
        total_opportunities=kpis.total,
        open_opportunities=kpis.open,
        closing_soon_opportunities=kpis.closing_soon,
        high_match_opportunities=kpis.high_match,
        top_scored=top_scored,
        closing_soon=closing_soon,
        status_breakdown=status_breakdown,
        country_breakdown=country_breakdown,
        degraded_sources=degraded_sources,
        failing_sources=failing_sources,
        source_alerts=source_alerts,
        data_coverage=data_coverage,
        profile=_profile_summary(profile),
    )


@router.get("/dashboard/triage", response_model=TriageRead)
def get_dashboard_triage(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    org: Organization = Depends(get_current_organization),
) -> TriageRead:
    """PR B-1a: action-oriented triage list for the consultor persona.

    Returns a short list of things to do today:

    * review_queue: items the user has marked for review or kept, ordered
      by close_date ASC (soonest first, NULL last).
    * closing_soon_7d: any opportunity closing within 7 days, regardless
      of user_status, ordered by close_date ASC.
    """
    return TriageRead(
        review_queue=get_review_queue(db, org.id, limit=8),
        closing_soon_7d=get_closing_soon_7d(db, org.id, limit=8),
    )


@router.get("/dashboard/pipeline", response_model=PipelineRead)
def get_dashboard_pipeline(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    org: Organization = Depends(get_current_organization),
) -> PipelineRead:
    """PR B-1b: lists lane of the dashboard for the consultor persona.

    Returns two focused slices:

    * top_scored — the highest-scoring opportunities for the current org,
      each with a numeric ``score`` and a list of ``reasons`` explaining it.
    * closing_soon — items whose close_date falls in [0, 30] days, ordered
      by close_date ASC (soonest first). Excludes already-closed
      (days_to_close < 0) and undated (close_date IS NULL) opportunities.
    """
    return PipelineRead(
        top_scored=get_top_scored(db, org.id, limit=8),
        closing_soon=get_closing_soon(db, org.id, limit=8, days_window=30),
    )


@router.get("/dashboard/health", response_model=HealthRead)
def get_dashboard_health(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    org: Organization = Depends(get_current_organization),
) -> HealthRead:
    """PR B-1c: health lane of the dashboard for the consultor persona."""
    cache_key = f"health:{org.id}"
    now_time = time.monotonic()
    entry = _health_cache.get(cache_key)
    if entry:
        ts, payload = entry
        if payload and (now_time - ts) < 60:
            return payload

    try:
        degraded, failing, source_alerts = get_source_health_summaries(db, org.id)
        kpis = get_health_kpis(db, org.id)
        status_bd = get_status_breakdown(db, org.id)
        country_bd = get_country_breakdown(db, org.id)
        coverage = get_data_coverage(db, org.id)
        sources_h = get_sources_health(db, org.id)
        score_dist = _safe_call(get_score_distribution, db, org.id)
        funding = _safe_call(get_funding_ranges, db, org.id)
        contrib = _safe_call(get_source_contribution, db, org.id)
        timeline = _safe_call(get_opportunities_timeline, db, org.id)
        cat_dist = _safe_call(get_category_distribution, db, org.id)
        payload = HealthRead(
            kpis=kpis, status_breakdown=status_bd, country_breakdown=country_bd,
            data_coverage=coverage, sources_health=sources_h,
            failing_sources=failing, degraded_sources=degraded, source_alerts=source_alerts,
            score_distribution=score_dist, funding_ranges=funding,
            source_contribution=contrib, opportunities_timeline=timeline,
            category_distribution=cat_dist,
        )
        _health_cache[cache_key] = (now_time, payload)
        return payload
    except Exception:
        # Fallback: return whatever we can without the analytics
        kpis = get_health_kpis(db, org.id)
        return HealthRead(
            kpis=kpis,
            status_breakdown=get_status_breakdown(db, org.id),
            country_breakdown=get_country_breakdown(db, org.id),
            data_coverage=get_data_coverage(db, org.id),
            sources_health=get_sources_health(db, org.id),
            failing_sources=0, degraded_sources=0, source_alerts=[],
        )


def _safe_call(fn, db, org_id):
    try:
        return fn(db, org_id)
    except Exception:
        return []
