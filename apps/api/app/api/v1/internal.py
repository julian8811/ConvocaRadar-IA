import hmac
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.email import send_email

from app.db.session import get_db
from app.models import Alert, AuditLog, Opportunity, Source, SourceRun, Task
from app.schemas import ConnectorProbeRequest, OpportunityCreate, SourceRunComplete
from app.services import candidate_external_id, connector_for, create_opportunity, create_source_health_alert, execute_source_run_locally, validate_source_url

router = APIRouter(prefix="/internal", tags=["internal"])


def verify_internal_key(x_internal_api_key: str | None = Header(default=None)) -> None:
    if not hmac.compare_digest(x_internal_api_key or "", get_settings().internal_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal API key")


@router.post("/source-runs/{run_id}/complete", dependencies=[Depends(verify_internal_key)])
def complete_source_run(
    run_id: str,
    payload: SourceRunComplete,
    db: Session = Depends(get_db),
) -> dict[str, int | str]:
    run = db.get(SourceRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Source run not found")
    source = db.get(Source, run.source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    task = db.get(Task, payload.task_id) if payload.task_id else None
    finished_at = datetime.now(UTC).replace(tzinfo=None)

    if payload.status == "failed":
        run.status = "failed"
        run.finished_at = finished_at
        run.error_message = payload.error_message or "Worker failed"
        run.items_found = payload.items_found
        run.items_failed = max(payload.items_found, 1)
        run.logs = [*run.logs, *payload.logs, {"level": "error", "message": run.error_message}]
        source.last_error = run.error_message
        if task:
            task.status = "failed"
            task.finished_at = finished_at
            task.error_message = run.error_message
            task.result = payload.model_dump()
        create_source_health_alert(db, source, reason=run.error_message)
        db.commit()
        return {"status": "failed", "items_created": 0, "items_updated": 0}

    created = 0
    updated = 0
    failed_items = 0
    for candidate in payload.items:
        try:
            external_id = candidate_external_id(source, candidate.official_url, candidate.title, candidate.raw_text or "")
            existing_opportunity = db.scalar(
                select(Opportunity).where(
                    Opportunity.source_id == source.id,
                    Opportunity.external_id == external_id,
                    (
                        (Opportunity.organization_id == source.organization_id)
                        if source.organization_id
                        else Opportunity.organization_id.is_(None)
                    ),
                )
            )
            create_opportunity(
                db,
                OpportunityCreate(
                    source_id=source.id,
                    external_id=external_id,
                    title=candidate.title,
                    entity=candidate.entity or source.name,
                    country=candidate.country or source.country,
                    categories=candidate.categories or source.category,
                    topics=candidate.topics,
                    summary=candidate.summary,
                    description=candidate.summary,
                    raw_text=candidate.raw_text,
                    official_url=candidate.official_url,
                    open_date=candidate.open_date,
                    close_date=candidate.close_date,
                    funding_amount_raw=candidate.funding_amount_raw,
                    requirements=candidate.requirements,
                    confidence_score=candidate.confidence_score,
                ),
                organization_id=source.organization_id,
            ),
            db.flush()
            if existing_opportunity:
                updated += 1
            else:
                created += 1
        except Exception as exc:
            failed_items += 1
            run.logs = [
                *run.logs,
                {
                    "level": "warning",
                    "message": "Candidate skipped during persistence",
                    "title": candidate.title,
                    "error": str(exc),
                },
            ]

    run.status = "degraded" if payload.items_found == 0 else "success"
    run.finished_at = finished_at
    run.items_found = payload.items_found
    run.items_created = created
    run.items_updated = updated
    run.items_failed = max(payload.items_invalid or (payload.items_found - payload.items_valid), 0) + failed_items
    run.logs = [
        *run.logs,
        *payload.logs,
        {
            "level": "info",
            "message": "Worker scrape completed",
            "items_valid": payload.items_valid,
            "items_created": created,
            "items_updated": updated,
            "items_failed": run.items_failed,
        },
    ]
    if payload.items_found > 0:
        source.last_success_at = finished_at
        source.last_error = None
    if payload.items_found == 0:
        create_source_health_alert(db, source, reason="no se detectaron oportunidades nuevas en la corrida del worker")
    if task:
        task.status = run.status
        task.finished_at = finished_at
        task.result = {**payload.model_dump(), "items_created": created, "items_updated": updated}
    db.add(
        AuditLog(
            organization_id=source.organization_id,
            action="complete_source_run",
            resource_type="source_run",
            resource_id=run.id,
        )
    )
    db.commit()
    return {"status": run.status, "items_created": created, "items_updated": updated}


@router.post("/connectors/probe", dependencies=[Depends(verify_internal_key)])
async def probe_connector(payload: ConnectorProbeRequest) -> dict[str, object]:
    connector = connector_for(payload.source_key, payload.base_url, payload.source_type)
    stats: dict[str, object] = {
        "source_key": payload.source_key,
        "base_url": payload.base_url,
        "source_type": payload.source_type,
    }
    try:
        raw = await connector.fetch()
        stats["raw_url"] = raw.url
        stats["raw_content_type"] = raw.content_type
        stats["raw_content_length"] = len(raw.content or "")
        candidates = await connector.parse(raw)
        stats["candidates_parsed"] = len(candidates)
        valid = 0
        validation_rejected = 0
        validation_reasons: list[str] = []
        for candidate in candidates:
            result = await connector.validate(candidate)
            if result.ok:
                valid += 1
                continue
            validation_rejected += 1
            if len(validation_reasons) < 5:
                validation_reasons.append(result.reason or "sin razon")
        stats["candidates_valid"] = valid
        stats["validation_rejected"] = validation_rejected
        stats["validation_reasons"] = validation_reasons
        return {"status": "ok", **stats}
    except Exception as exc:
        stats["error"] = str(exc)
        return {"status": "error", **stats}


@router.post("/scheduler/sources/run-enabled", dependencies=[Depends(verify_internal_key)])
def run_enabled_sources(db: Session = Depends(get_db)) -> dict[str, int]:
    sources = list(db.scalars(select(Source).where(Source.enabled.is_(True))))
    runs_created = 0
    failed = 0
    for source in sources:
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
            organization_id=source.organization_id,
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
            db.delete(task)
            db.delete(run)
            db.flush()
            run = execute_source_run_locally(db, source, organization_id=source.organization_id)
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
            failed += 1
        runs_created += 1
        db.add(
            AuditLog(
                organization_id=source.organization_id,
                action="scheduled_source_run",
                resource_type="source_run",
                resource_id=run.id,
            )
        )
    db.commit()
    return {"sources_checked": len(sources), "runs_created": runs_created, "failed": failed}


@router.post("/scheduler/sources/retry-degraded", dependencies=[Depends(verify_internal_key)])
def retry_degraded_sources(db: Session = Depends(get_db)) -> dict[str, int]:
    sources = list(db.scalars(select(Source).where(Source.enabled.is_(True))))
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
        create_source_health_alert(db, source, reason=f"fuente {health}; reintento ejecutado")
        scheduled += 1
    db.commit()
    return {"sources_checked": len(sources), "scheduled": scheduled, "skipped": skipped}


@router.post("/scheduler/alerts/send-due", dependencies=[Depends(verify_internal_key)])
def send_due_alerts(db: Session = Depends(get_db)) -> dict[str, int]:
    now = datetime.now(UTC).replace(tzinfo=None)
    alerts = list(
        db.scalars(
            select(Alert).where(
                Alert.status == "pending",
                Alert.channel == "email",
                Alert.scheduled_at.is_not(None),
                Alert.scheduled_at <= now,
            )
        )
    )
    sent = 0
    failed = 0
    for alert in alerts:
        try:
            send_email(recipient=alert.recipient, subject=alert.subject, message=alert.message)
            alert.status = "sent"
            alert.sent_at = now
            sent += 1
        except Exception as exc:
            alert.status = "failed"
            alert.sent_at = None
            failed += 1
            db.add(
                AuditLog(
                    organization_id=alert.organization_id,
                    action="scheduled_alert_failed",
                    resource_type="alert",
                    resource_id=alert.id,
                    metadata_json={"error": str(exc)},
                )
            )
            continue
        db.add(
            AuditLog(
                organization_id=alert.organization_id,
                action="scheduled_alert_sent",
                resource_type="alert",
                resource_id=alert.id,
            )
        )
    db.commit()
    return {"alerts_checked": len(alerts), "sent": sent, "failed": failed}
