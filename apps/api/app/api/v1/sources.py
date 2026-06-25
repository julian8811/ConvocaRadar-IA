from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_organization, get_current_user
from app.db.session import get_db
from app.models import Organization, Source, SourceRun, User
from app.schemas import SourceCreate, SourceHealthRead, SourceRead, SourceRunRead, SourceUpdate
from app.services import audit, execute_source_run_locally, schedule_or_execute_source_run, source_due_for_scraping, validate_source_url

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
    run = execute_source_run_locally(db, source, organization_id=organization.id)
    audit(db, "run_source", "source_run", user, run.id)
    db.commit()
    db.refresh(run)
    return run


@router.post("/sources/run-all", response_model=list[SourceRunRead])
def run_all_sources(
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SourceRun]:
    sources = list(
        db.scalars(
            select(Source).where(
                Source.enabled.is_(True),
                (Source.organization_id == organization.id) | (Source.organization_id.is_(None)),
            )
        )
    )
    runs: list[SourceRun] = []
    for source in sources:
        if not source_due_for_scraping(source):
            continue
        run = schedule_or_execute_source_run(db, source, organization_id=organization.id)
        audit(db, "run_source", "source_run", user, run.id)
        runs.append(run)
    db.commit()
    for run in runs:
        db.refresh(run)
    return runs


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
