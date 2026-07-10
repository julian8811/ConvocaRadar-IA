from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_organization, get_current_user
from app.db.session import get_db
from app.services import execute_source_run_locally
from app.models import Alert, AuditLog, Opportunity, OpportunityEmbedding, Organization, Report, Role, Source, SourceRun, Task, User
from app.schemas import AdminMetricsRead, AuditLogRead, SourceRunOverviewRead
from app.db.bootstrap import bootstrap_priority_sources
from app.db.seed import seed_default_sources
from app.services import (
    audit,
    backfill_close_dates,
    backfill_close_dates_ai,
    backfill_funding_amounts,
    backfill_funding_amounts_ai,
    deduplicate_opportunities,
    execute_source_run_locally,
    rebuild_opportunity_embeddings,
    rescore_all_opportunities,
    score_unscored_opportunities,
    send_weekly_digest,
    summarize_missing_opportunities,
)

router = APIRouter()


def _health_window_days(source: Source) -> int:
    frequency = (source.scraping_frequency or "").lower()
    if frequency in {"hourly", "every_hour"}:
        return 1
    if frequency in {"daily", "every_day"}:
        return 3
    if frequency in {"weekly", "every_week"}:
        return 10
    if frequency in {"monthly", "every_month"}:
        return 40
    return 7


def _days_since_last_success(recent_runs: list[SourceRun], source: Source) -> int | None:
    last_success = next((run for run in recent_runs if run.status == "success" and run.finished_at), None)
    success_at = last_success.finished_at if last_success else source.last_success_at
    if not success_at:
        return None
    return max((datetime.now(UTC).replace(tzinfo=None) - success_at).days, 0)


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.admin.value:
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


def _source_health_status(db: Session, source: Source, raw_recent_runs: list[SourceRun] | None = None) -> str:
    if raw_recent_runs is None:
        raw_recent_runs = list(
            db.scalars(
                select(SourceRun)
                .where(SourceRun.source_id == source.id)
                .order_by(SourceRun.created_at.desc())
                .limit(10)
            )
        )
    recent_runs = [run for run in raw_recent_runs if run.status in {"success", "failed", "degraded"}]
    failures = sum(1 for run in recent_runs if run.status == "failed")
    days_since_last_success = _days_since_last_success(recent_runs, source)
    stale_days = _health_window_days(source)
    if not raw_recent_runs:
        return "idle"
    if not recent_runs:
        return "idle"
    if recent_runs[0].status == "failed":
        return "failing"
    if recent_runs[0].status == "degraded":
        return "degraded"
    success_rate = round((sum(1 for run in recent_runs if run.status == "success") / len(recent_runs)) * 100, 2)
    average_items_found = round(sum(run.items_found for run in recent_runs) / len(recent_runs), 2)
    failure_rate = round((failures / len(recent_runs)) * 100, 2)
    if (
        (failure_rate >= 60 and average_items_found <= 1)
        or (days_since_last_success is not None and days_since_last_success >= stale_days * 2)
    ):
        return "failing"
    if (
        success_rate < 60
        or (average_items_found <= 0 and len(recent_runs) >= 2)
        or (days_since_last_success is not None and days_since_last_success >= stale_days)
    ):
        return "degraded"
    return "healthy"


@router.get("/admin/audit-logs", response_model=list[AuditLogRead])
def list_audit_logs(
    organization: Organization = Depends(get_current_organization),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.organization_id == organization.id)
            .order_by(AuditLog.created_at.desc())
            .limit(50)
        )
    )


@router.get("/admin/source-runs", response_model=list[SourceRunOverviewRead])
def list_recent_source_runs(
    organization: Organization = Depends(get_current_organization),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    source_scope = or_(Source.organization_id == organization.id, Source.organization_id.is_(None))
    rows = list(
        db.execute(
            select(SourceRun, Source.key, Source.name)
            .join(Source, Source.id == SourceRun.source_id)
            .where(source_scope)
            .order_by(SourceRun.created_at.desc())
            .limit(25)
        )
    )
    return [
        {
            "id": source_run.id,
            "source_id": source_run.source_id,
            "status": source_run.status,
            "started_at": source_run.started_at,
            "finished_at": source_run.finished_at,
            "items_found": source_run.items_found,
            "items_created": source_run.items_created,
            "items_updated": source_run.items_updated,
            "items_failed": source_run.items_failed,
            "error_message": source_run.error_message,
            "logs": source_run.logs,
            "created_at": source_run.created_at,
            "source_key": source_key,
            "source_name": source_name,
        }
        for source_run, source_key, source_name in rows
    ]


@router.get("/admin/metrics", response_model=AdminMetricsRead)
def get_admin_metrics(
    organization: Organization = Depends(get_current_organization),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminMetricsRead:
    source_scope = or_(Source.organization_id == organization.id, Source.organization_id.is_(None))
    opportunity_scope = or_(Opportunity.organization_id == organization.id, Opportunity.organization_id.is_(None))
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

    source_health_counts = {
        "degraded": sum(1 for source in sources if _source_health_status(db, source, runs_by_source.get(source.id, [])) == "degraded"),
        "failing": sum(1 for source in sources if _source_health_status(db, source, runs_by_source.get(source.id, [])) == "failing"),
    }
    stale_sources = sum(
        1
        for source in sources
        if source.last_success_at is not None and (datetime.now(UTC).replace(tzinfo=None) - source.last_success_at).days >= _health_window_days(source)
    )
    opportunity_total = db.scalar(select(func.count()).select_from(Opportunity).where(opportunity_scope)) or 0
    embeddings_total = db.scalar(
        select(func.count()).select_from(OpportunityEmbedding).join(
            Opportunity, Opportunity.id == OpportunityEmbedding.opportunity_id
        ).where(opportunity_scope)
    ) or 0
    embeddings_missing = max(opportunity_total - embeddings_total, 0)
    embeddings_coverage = round((embeddings_total / opportunity_total) * 100, 1) if opportunity_total else 0.0

    return AdminMetricsRead(
        active_sources=db.scalar(select(func.count()).select_from(Source).where(source_scope, Source.enabled.is_(True))) or 0,
        total_sources=db.scalar(select(func.count()).select_from(Source).where(source_scope)) or 0,
        degraded_sources=source_health_counts["degraded"],
        failing_sources=source_health_counts["failing"],
        stale_sources=stale_sources,
        opportunities=opportunity_total,
        open_opportunities=db.scalar(select(func.count()).select_from(Opportunity).where(opportunity_scope, Opportunity.status == "open")) or 0,
        closing_soon_opportunities=db.scalar(
            select(func.count()).select_from(Opportunity).where(opportunity_scope, Opportunity.status == "closing_soon")
        )
        or 0,
        embeddings_total=embeddings_total,
        embeddings_missing=embeddings_missing,
        embeddings_coverage=embeddings_coverage,
        failed_source_runs=db.scalar(
            select(func.count())
            .select_from(SourceRun)
            .join(Source, Source.id == SourceRun.source_id)
            .where(source_scope, SourceRun.status == "failed")
        )
        or 0,
        failed_tasks=db.scalar(select(func.count()).select_from(Task).where(Task.organization_id == organization.id, Task.status == "failed")) or 0,
        reports=db.scalar(select(func.count()).select_from(Report).where(Report.organization_id == organization.id)) or 0,
        pending_alerts=db.scalar(select(func.count()).select_from(Alert).where(Alert.organization_id == organization.id, Alert.status == "pending")) or 0,
        source_health_alerts=db.scalar(
            select(func.count()).select_from(Alert).where(
                Alert.organization_id == organization.id,
                Alert.alert_type == "source_health",
                Alert.status == "pending",
            )
        )
        or 0,
        sent_alerts=db.scalar(select(func.count()).select_from(Alert).where(Alert.organization_id == organization.id, Alert.status == "sent")) or 0,
        audit_events=db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.organization_id == organization.id)) or 0,
    )


@router.post("/admin/sources/reseed-defaults")
def reseed_default_sources_admin(
    force: bool = False,
    organization: Organization = Depends(get_current_organization),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    """Reseed the default source catalog for the calling org.

    By default (``force=false``), sources already owned by another org are
    SKIPPED — the seed will not steal them. Pass ``?force=true`` as an
    explicit admin opt-in to bypass the org-ownership safety check and
    reassign/update every source.
    """
    before_total = db.scalar(
        select(func.count()).select_from(Source).where(
            or_(Source.organization_id == organization.id, Source.organization_id.is_(None))
        )
    ) or 0
    stats = seed_default_sources(db, organization, force=force)
    after_total = db.scalar(
        select(func.count()).select_from(Source).where(
            or_(Source.organization_id == organization.id, Source.organization_id.is_(None))
        )
    ) or 0
    db.add(
        AuditLog(
            organization_id=organization.id,
            action="reseed_default_sources",
            resource_type="source",
            resource_id=organization.id,
            metadata_json={
                **stats,
                "force": force,
                "before_total": before_total,
                "after_total": after_total,
            },
        )
    )
    db.commit()
    return {**stats, "force": force, "before_total": before_total, "after_total": after_total}


@router.post("/admin/opportunities/summarize-all")
def summarize_all_opportunities_admin(
    limit: int = 10,
    organization: Organization = Depends(get_current_organization),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    """Generate AI summaries for opportunities that have none.

    Bounded to ``limit`` per call to stay under the Gemini free-tier quota.
    The endpoint is safe to call repeatedly; opportunities with a non-empty
    summary are skipped.
    """
    result = summarize_missing_opportunities(db, organization.id, limit=limit)
    db.add(
        AuditLog(
            organization_id=organization.id,
            action="summarize_all_opportunities",
            resource_type="opportunity",
            resource_id=organization.id,
            metadata_json={**result, "limit": limit},
        )
    )
    db.commit()
    return result


@router.post("/admin/opportunities/score-all")
def score_all_opportunities_admin(
    limit: int = 10,
    organization: Organization = Depends(get_current_organization),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    """Generate OpportunityScore rows for unscored opportunities for this org.

    Bounded to ``limit`` per call. Opportunities that already have a score
    for this organization are skipped. The score uses the same heuristic as
    the per-opportunity ``POST /opportunities/{id}/scores`` endpoint.
    """
    result = score_unscored_opportunities(db, organization.id, limit=limit)
    db.add(
        AuditLog(
            organization_id=organization.id,
            action="score_all_opportunities",
            resource_type="opportunity",
            resource_id=organization.id,
            metadata_json={**result, "limit": limit},
        )
    )
    db.commit()
    return result


@router.post("/admin/opportunities/rescore-all")
def rescore_all_opportunities_admin(
    limit: int = 10,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Recalculate scores for ALL opportunities using the new multi-dimensional
    scorer (overwrites existing scores). Runs on up to ``limit`` per call.
    """
    result = rescore_all_opportunities(db, organization.id, limit=limit)
    db.add(
        AuditLog(
            organization_id=organization.id,
            user_id=user.id,
            action="rescore_all_opportunities",
            resource_type="opportunity",
            resource_id=organization.id,
            metadata_json={**result, "limit": limit},
        )
    )
    db.commit()
    return result


@router.post("/admin/alerts/send-digest")
def send_digest_admin(
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, bool | int]:
    """Manually trigger the weekly digest email for this organization.

    Returns ``{"delivered": bool, "opportunities": int}`` so the frontend can
    show a meaningful toast. ``delivered=False`` may simply mean SMTP is not
    configured (the existing ``send_email`` records a dev dry-run in that
    case), or that the org has no admin recipient.
    """
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=7)
    scope = or_(Opportunity.organization_id == organization.id, Opportunity.organization_id.is_(None))
    opportunity_count = db.scalar(
        select(func.count()).select_from(Opportunity).where(scope, Opportunity.created_at >= cutoff)
    ) or 0
    delivered = send_weekly_digest(db, organization.id)
    db.add(
        AuditLog(
            organization_id=organization.id,
            user_id=user.id,
            action="send_weekly_digest",
            resource_type="alert",
            resource_id=organization.id,
            metadata_json={"delivered": delivered, "opportunities": int(opportunity_count)},
        )
    )
    db.commit()
    return {"delivered": delivered, "opportunities": int(opportunity_count)}


@router.post("/admin/opportunities/deduplicate")
def deduplicate_opportunities_admin(
    organization: Organization = Depends(get_current_organization),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    stats = deduplicate_opportunities(db, organization.id)
    db.add(
        AuditLog(
            organization_id=organization.id,
            action="deduplicate_opportunities",
            resource_type="opportunity",
            resource_id=organization.id,
            metadata_json=stats,
        )
    )
    db.commit()
    return stats


@router.post("/admin/sources/retry-degraded")
def retry_degraded_sources_admin(
    organization: Organization = Depends(get_current_organization),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    source_scope = or_(Source.organization_id == organization.id, Source.organization_id.is_(None))
    sources = list(db.scalars(select(Source).where(source_scope, Source.enabled.is_(True))))
    scheduled = 0
    skipped = 0
    for source in sources:
        recent_runs = list(
            db.scalars(
                select(SourceRun)
                .where(SourceRun.source_id == source.id)
                .order_by(SourceRun.created_at.desc())
                .limit(5)
            )
        )
        if not recent_runs:
            continue
        failures = sum(1 for run in recent_runs if run.status == "failed")
        health = "failing" if recent_runs[0].status == "failed" or failures >= 3 else "degraded" if failures > 0 else "healthy"
        if health == "healthy":
            continue
        pending_task = db.scalar(
            select(Task)
            .join(SourceRun, SourceRun.id == Task.source_run_id)
            .where(
                SourceRun.source_id == source.id,
                Task.source_run_id.is_not(None),
                Task.task_type == "scrape_source",
                Task.status.in_(["running", "queued", "scheduled"]),
            )
        )
        if pending_task:
            skipped += 1
            continue
        execute_source_run_locally(db, source, organization_id=source.organization_id)
        scheduled += 1
    db.commit()
    return {"sources_checked": len(sources), "scheduled": scheduled, "skipped": skipped}


@router.post("/admin/embeddings/rebuild")
async def rebuild_embeddings_admin(
    organization: Organization = Depends(get_current_organization),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
    limit: int | None = None,
) -> dict[str, int]:
    result = await rebuild_opportunity_embeddings(db, organization.id, limit=limit)
    db.add(
        AuditLog(
            organization_id=organization.id,
            action="rebuild_opportunity_embeddings",
            resource_type="opportunity_embedding",
            resource_id=organization.id,
            metadata_json={"limit": limit, **result},
        )
    )
    db.commit()
    return result


@router.post("/admin/bootstrap-data")
def bootstrap_data_admin(
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, int | str]:
    result = bootstrap_priority_sources(blocking=True) or {"status": "skipped", "reason": "bootstrap_disabled"}
    db.add(
        AuditLog(
            organization_id=organization.id,
            user_id=user.id,
            action="bootstrap_priority_sources",
            resource_type="source",
            resource_id=organization.id,
            metadata_json=result if isinstance(result, dict) else {"status": str(result)},
        )
    )
    db.commit()
    return result


@router.post("/admin/opportunities/backfill-funding")
def backfill_funding_admin(
    limit: int = 500,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Parse existing ``funding_amount_raw`` strings into numeric value + currency
    without calling the LLM. Uses local regex patterns. Runs on up to ``limit``
    opportunities per call.
    """
    org_id = user.organization_id
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no organization")
    result = backfill_funding_amounts(db, org_id, limit=limit)
    audit(db, "backfill_funding_amounts", "opportunity", user, org_id)
    db.commit()
    return result


@router.post("/admin/opportunities/backfill-close-dates")
def backfill_close_dates_admin(
    limit: int = 500,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Extract ``close_date`` from existing title/summary/description/raw_text
    for opportunities that are missing it. Uses local regex — no AI calls.
    """
    org_id = user.organization_id
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no organization")
    result = backfill_close_dates(db, org_id, limit=limit)
    audit(db, "backfill_close_dates", "opportunity", user, org_id)
    db.commit()
    return result


@router.post("/admin/opportunities/backfill-close-dates-ai")
def backfill_close_dates_ai_admin(
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Use AI (LLM) to extract ``close_date`` for opportunities missing it.

    Calls the LLM (Groq) on each opportunity's text to find close dates
    that regex patterns miss. More expensive but more thorough. Keep
    batches small (10-50) due to API cost and latency.
    """
    org_id = user.organization_id
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no organization")
    result = backfill_close_dates_ai(db, org_id, limit=limit)
    audit(db, "backfill_close_dates_ai", "opportunity", user, org_id)
    db.commit()
    return result


@router.post("/admin/opportunities/backfill-funding-ai")
def backfill_funding_amounts_ai_admin(
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Use AI (LLM) to extract ``funding_amount_raw`` for opportunities missing it.

    Calls the LLM (Groq) on each opportunity's text to find funding amounts
    that regex patterns miss. Batch small (10-50) due to token cost.
    """
    org_id = user.organization_id
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no organization")
    result = backfill_funding_amounts_ai(db, org_id, limit=limit)
    audit(db, "backfill_funding_amounts_ai", "opportunity", user, org_id)
    db.commit()
    return result


@router.post("/admin/sources/clear-errors")
def clear_source_errors(
    error_pattern: str = Query(default="", description="Clear only sources whose last_error contains this text (case-insensitive). Empty = all."),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Clear ``last_error``, ``last_success_at``, and mark enabled sources as healthy.

    Useful after a code deploy that fixes a root cause — rather than waiting
    for each source's daily scrape to clear the stale error, this endpoint
    resets them immediately so the dashboard reflects the fix.

    With ``error_pattern``, only sources whose ``last_error`` contains the
    given text are cleared (e.g. ``?error_pattern=entity_name``).
    """
    scope = select(Source).where(Source.enabled.is_(True))
    if error_pattern:
        scope = scope.where(Source.last_error.ilike(f"%{error_pattern}%"))
    sources = list(db.scalars(scope))
    cleared = 0
    for source in sources:
        if source.last_error:
            source.last_error = None
            cleared += 1
    db.commit()
    audit(db, "clear_source_errors", "source", user, str(cleared))
    return {"total": len(sources), "cleared": cleared, "error_pattern": error_pattern or "all"}
