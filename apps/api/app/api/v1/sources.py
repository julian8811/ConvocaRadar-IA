from datetime import UTC, datetime
import logging

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_organization, get_current_user
from app.db.seed import seed_default_sources
from app.db.session import get_db, SessionLocal
from app.models import Organization, Source, SourceRun, User
from app.schemas import SourceCreate, SourceHealthRead, SourceRead, SourceRunRead, SourceUpdate
from app.services import audit, execute_source_run_locally, schedule_or_execute_source_run, source_due_for_scraping, validate_source_url

router = APIRouter()
logger = logging.getLogger(__name__)
struct_logger = structlog.get_logger(__name__)


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


@router.get("/sources", response_model=list[SourceRead])
def list_sources(
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> list[Source]:
    return list(
        db.scalars(
            select(Source).where((Source.organization_id == organization.id) | (Source.organization_id.is_(None)))
        )
    )


@router.post("/sources", response_model=SourceRead)
def create_source(
    payload: SourceCreate,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Source:
    source = Source(**payload.model_dump(), organization_id=organization.id)
    try:
        validate_source_url(source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.add(source)
    db.flush()
    audit(db, "create_source", "source", user, source.id)
    db.commit()
    db.refresh(source)
    return source


def _get_source_for_org(db: Session, source_id: str, organization: Organization) -> Source:
    source = db.scalar(
        select(Source).where(
            Source.id == source_id,
            (Source.organization_id == organization.id) | (Source.organization_id.is_(None)),
        )
    )
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


def _source_health(db: Session, source: Source) -> SourceHealthRead:
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
    recent_items_found = sum(run.items_found for run in recent_runs)
    recent_items_created = sum(run.items_created for run in recent_runs)
    recent_items_updated = sum(run.items_updated for run in recent_runs)
    last_run_status = raw_recent_runs[0].status if raw_recent_runs else None
    last_run_duration_seconds = None
    last_completed_run = recent_runs[0] if recent_runs else None
    if last_completed_run and last_completed_run.started_at and last_completed_run.finished_at:
        last_run_duration_seconds = max((last_completed_run.finished_at - last_completed_run.started_at).total_seconds(), 0.0)
    successful_runs = sum(1 for run in recent_runs if run.status == "success")
    run_count = len(recent_runs)
    success_rate = round((successful_runs / run_count) * 100, 2) if run_count else 0.0
    failure_rate = round((failures / run_count) * 100, 2) if run_count else 0.0
    average_items_found = round(recent_items_found / run_count, 2) if run_count else 0.0
    days_since_last_success = _days_since_last_success(recent_runs, source)
    stale_days = _health_window_days(source)
    if not raw_recent_runs:
        status = "idle"
    elif not recent_runs:
        status = "idle"
    elif recent_runs[0].status == "failed":
        status = "failing"
    elif recent_runs[0].status == "degraded":
        status = "degraded"
    elif (
        (failure_rate >= 60 and average_items_found <= 1)
        or (days_since_last_success is not None and days_since_last_success >= stale_days * 2)
    ):
        status = "failing"
    elif (
        success_rate < 60
        or (average_items_found <= 0 and run_count >= 2)
        or (days_since_last_success is not None and days_since_last_success >= stale_days)
    ):
        status = "degraded"
    else:
        status = "healthy"
    return SourceHealthRead(
        source_id=source.id,
        key=source.key,
        name=source.name,
        source_type=source.source_type,
        status=status,
        last_run_at=source.last_run_at,
        last_success_at=source.last_success_at,
        last_error=source.last_error,
        recent_runs=len(recent_runs),
        recent_failures=failures,
        recent_items_found=recent_items_found,
        recent_items_created=recent_items_created,
        recent_items_updated=recent_items_updated,
        success_rate=success_rate,
        failure_rate=failure_rate,
        average_items_found=average_items_found,
        last_run_duration_seconds=last_run_duration_seconds,
        days_since_last_success=days_since_last_success,
        last_run_status=last_run_status,
    )


@router.get("/sources/health", response_model=list[SourceHealthRead])
def list_sources_health(
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> list[SourceHealthRead]:
    sources = list(
        db.scalars(
            select(Source).where((Source.organization_id == organization.id) | (Source.organization_id.is_(None)))
        )
    )
    return [_source_health(db, source) for source in sources]


@router.get("/sources/{source_id}", response_model=SourceRead)
def get_source(
    source_id: str,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> Source:
    return _get_source_for_org(db, source_id, organization)


@router.patch("/sources/{source_id}", response_model=SourceRead)
def update_source(
    source_id: str,
    payload: SourceUpdate,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Source:
    source = _get_source_for_org(db, source_id, organization)
    if source.organization_id != organization.id:
        raise HTTPException(status_code=403, detail="Shared sources cannot be modified")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(source, key, value)
    try:
        validate_source_url(source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(db, "update_source", "source", user, source.id)
    db.commit()
    db.refresh(source)
    return source


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(
    source_id: str,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    source = _get_source_for_org(db, source_id, organization)
    if source.organization_id != organization.id:
        raise HTTPException(status_code=403, detail="Shared sources cannot be deleted")
    if source:
        audit(db, "delete_source", "source", user, source.id)
        db.delete(source)
        db.commit()


@router.post("/sources/{source_id}/run", response_model=SourceRunRead)
def run_source(
    source_id: str,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SourceRun:
    source = _get_source_for_org(db, source_id, organization)
    # Use schedule_or_execute_source_run (not execute_source_run_locally) so
    # heavy HTML sources (apc-colombia, minciencias, etc.) are dispatched to
    # the Celery worker instead of blocking the request for 60-120s.
    # See PR5 + services.py for the routing logic.
    run = schedule_or_execute_source_run(db, source, organization_id=organization.id)
    audit(db, "run_source", "source_run", user, run.id)
    db.commit()
    db.refresh(run)
    return run


@router.post("/sources/run-all", response_model=dict)
def run_all_sources(
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Start a background sweep of all enabled sources.

    The sweep runs in a daemon thread so the HTTP response returns
    immediately. Use GET /api/v1/sources/health to monitor progress.

    PR4-2: structured log lines are emitted at every decision point so
    the run-all empty-return bug can be diagnosed from the log output:
    - ``run_all.sources_loaded`` — how many sources were loaded
    - ``run_all.skip`` — per-source skip reason (frequency, last_run_at, elapsed)
    - ``run_all.completed`` — final processed/skipped counts

    The per-source decision logs are emitted SYNCHRONOUSLY (before the
    background thread starts) so the run-all empty-return bug can be
    diagnosed from a single request's log output — the same request
    that returned an empty run list.
    """
    import threading

    sources = list(
        db.scalars(
            select(Source).where(
                Source.enabled.is_(True),
                (Source.organization_id == organization.id) | (Source.organization_id.is_(None)),
            )
        )
    )
    org_id = organization.id
    struct_logger.info(
        "run_all.sources_loaded",
        sources_loaded=len(sources),
        org_id=org_id,
    )

    # Pre-compute the per-source due/skip decisions synchronously so the
    # diagnostic logs are emitted in the request's log context (visible to
    # the operator who triggered the empty-return bug). The actual scrape
    # execution is still dispatched to the background thread.
    now = datetime.now(UTC).replace(tzinfo=None)
    due_sources: list[Source] = []
    for source in sources:
        if source_due_for_scraping(source, now=now):
            struct_logger.info(
                "run_all.process",
                source_id=str(source.id),
                source_key=source.key,
                reason="due",
                frequency=(source.scraping_frequency or "daily").lower(),
            )
            due_sources.append(source)
        else:
            frequency = (source.scraping_frequency or "daily").lower()
            last_run = source.last_run_at
            elapsed_seconds = (
                (now - last_run).total_seconds() if last_run else None
            )
            struct_logger.info(
                "run_all.skip",
                source_id=str(source.id),
                source_key=source.key,
                reason="not_due",
                frequency=frequency,
                last_run_at=last_run.isoformat() if last_run else None,
                elapsed_seconds=elapsed_seconds,
            )
    struct_logger.info(
        "run_all.decision_summary",
        sources_due=len(due_sources),
        sources_skipped=len(sources) - len(due_sources),
        total=len(sources),
    )

    def _background_sweep() -> None:
        db2 = SessionLocal()
        processed = 0
        failed = 0
        try:
            for source in due_sources:
                fresh = db2.merge(source)
                try:
                    execute_source_run_locally(db2, fresh, organization_id=org_id)
                    processed += 1
                except Exception as exc:
                    # PR4-4: log the failure with full context so the
                    # run-all empty-run-list bug can be diagnosed from
                    # the log output. Previously this except silently
                    # swallowed the error and the operator had no
                    # way to know why runs were not being created.
                    db2.rollback()
                    failed += 1
                    struct_logger.error(
                        "run_all.source_failed",
                        source_id=str(fresh.id),
                        source_key=fresh.key,
                        error_type=type(exc).__name__,
                        error_message=str(exc)[:500],
                    )
            db2.commit()
            struct_logger.info(
                "run_all.completed",
                processed=processed,
                failed=failed,
                total=len(due_sources),
            )
        finally:
            db2.close()

    threading.Thread(target=_background_sweep, daemon=True).start()
    audit(db, "run_source_sweep_dispatched", "source_sweep", user, None)
    return {"status": "started", "sources": len(sources)}


@router.get("/sources/{source_id}/runs", response_model=list[SourceRunRead])
def list_runs(
    source_id: str,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> list[SourceRun]:
    _get_source_for_org(db, source_id, organization)
    return list(db.scalars(select(SourceRun).where(SourceRun.source_id == source_id).order_by(SourceRun.created_at.desc())))


@router.get("/source-runs/{run_id}", response_model=SourceRunRead)
def get_run(
    run_id: str,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> SourceRun:
    run = db.scalar(
        select(SourceRun)
        .join(Source, Source.id == SourceRun.source_id)
        .where(
            SourceRun.id == run_id,
            (Source.organization_id == organization.id) | (Source.organization_id.is_(None)),
        )
    )
    if not run:
        raise HTTPException(status_code=404, detail="Source run not found")
    return run


@router.get("/sources/{source_id}/health", response_model=SourceHealthRead)
def get_source_health(
    source_id: str,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> SourceHealthRead:
    source = _get_source_for_org(db, source_id, organization)
    return _source_health(db, source)


@router.post("/sources/claim-defaults")
def claim_default_sources(
    force: bool = False,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    """Claim or reseed the default source catalog for the calling org.

    Any non-admin user can call this when their org has no sources.
    With ``force=true``, even sources owned by another org are reassigned.
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
    db.commit()
    audit(db, "claim_default_sources", "source", user, organization.id)
    return {**stats, "force": force, "before_total": before_total, "after_total": after_total}
