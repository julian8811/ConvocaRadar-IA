from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_organization, get_current_user
from app.db.session import get_db
from app.core.task_queue import enqueue_scrape_source
from app.models import Alert, AuditLog, Opportunity, OpportunityEmbedding, Organization, Report, Source, SourceRun, Task, User
from app.schemas import AdminMetricsRead, AuditLogRead, SourceRunOverviewRead
from app.services import rebuild_opportunity_embeddings

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
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


def _source_health_status(db: Session, source: Source) -> str:
    recent_runs = list(
        db.scalars(
            select(SourceRun)
            .where(SourceRun.source_id == source.id)
            .order_by(SourceRun.created_at.desc())
            .limit(10)
        )
    )
    failures = sum(1 for run in recent_runs if run.status == "failed")
    days_since_last_success = _days_since_last_success(recent_runs, source)
    stale_days = _health_window_days(source)
    if not recent_runs:
        return "idle"
    if recent_runs[0].status == "failed":
        return "failing"
    success_rate = round((sum(1 for run in recent_runs if run.status == "success") / len(recent_runs)) * 100, 2)
    average_items_found = round(sum(run.items_found for run in recent_runs) / len(recent_runs), 2)
    failure_rate = round((failures / len(recent_runs)) * 100, 2)
    if (
        (failure_rate >= 60 and average_items_found <= 1)
        or (days_since_last_success is not None and days_since_last_success >= stale_days * 2)
    ):
        return "failing"
    if failures > 0 or (days_since_last_success is not None and days_since_last_success >= stale_days):
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
    source_health_counts = {
        "degraded": sum(1 for source in sources if _source_health_status(db, source) == "degraded"),
        "failing": sum(1 for source in sources if _source_health_status(db, source) == "failing"),
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
        started_at = datetime.now(UTC).replace(tzinfo=None)
        run = SourceRun(
            source_id=source.id,
            status="scheduled",
            started_at=None,
            logs=[{"level": "info", "message": "Retry scheduled from admin", "health": health}],
        )
        db.add(run)
        db.flush()
        task = Task(
            organization_id=source.organization_id,
            source_run_id=run.id,
            task_type="scrape_source",
            provider="celery",
            status="scheduled",
            started_at=started_at,
            payload={"source_key": source.key, "base_url": source.base_url, "source_type": source.source_type},
        )
        db.add(task)
        db.flush()
        external_id = enqueue_scrape_source(
            source.key,
            source.base_url,
            source.source_type,
            source_run_id=run.id,
            task_id=task.id,
            countdown_seconds=900,
        )
        task.external_id = external_id
        task.result = {"message": "Retry scheduled in 15 minutes", "health": health}
        db.add(
            AuditLog(
                organization_id=source.organization_id,
                action="schedule_source_retry",
                resource_type="source_run",
                resource_id=run.id,
            )
        )
        scheduled += 1
    db.commit()
    return {"sources_checked": len(sources), "scheduled": scheduled, "skipped": skipped}


@router.post("/admin/embeddings/rebuild")
def rebuild_embeddings_admin(
    organization: Organization = Depends(get_current_organization),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
    limit: int | None = None,
) -> dict[str, int]:
    result = rebuild_opportunity_embeddings(db, organization.id, limit=limit)
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
