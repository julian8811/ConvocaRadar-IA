from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_organization, get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models import Organization, Role, Task, User
from app.schemas import TaskRead

router = APIRouter()

# Boot del proceso actual (UTC naive, como el resto del módulo). Un sweep
# sin terminar creado ANTES de este instante es huérfano por restart y se
# libera; uno creado DESPUÉS vive en este proceso y nunca es stale, tenga
# la edad que tenga (un barrido completo tarda 25-40 min). Vale porque api
# corre single-process (uvicorn sin --workers): con N workers habría que
# revisarlo (un worker marcaría como rancios los sweeps de otro).
_PROCESS_BOOTED_AT = datetime.now(UTC).replace(tzinfo=None)


def _mark_stale_source_sweeps(db: Session, organization_id: str) -> None:
    """Release UI locks left by a process restart during a source sweep."""
    stale = list(
        db.scalars(
            select(Task).where(
                Task.organization_id == organization_id,
                Task.task_type == "source_sweep",
                Task.status.in_(("queued", "running")),
                Task.finished_at.is_(None),
                Task.created_at < _PROCESS_BOOTED_AT,
            )
        )
    )
    if not stale:
        return
    finished_at = datetime.now(UTC).replace(tzinfo=None)
    for task in stale:
        task.status = "failed"
        task.finished_at = finished_at
        task.error_message = "La ejecución se interrumpió antes de finalizar"
    db.commit()


@router.get("/tasks", response_model=list[TaskRead])
def list_tasks(
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> list[Task]:
    _mark_stale_source_sweeps(db, organization.id)
    return list(
        db.scalars(
            select(Task)
            .where(Task.organization_id == organization.id)
            .order_by(Task.created_at.desc())
            .limit(100)
        )
    )


@router.post("/tasks/archive")
def archive_old_tasks(
    older_than_days: int = Query(default=30, ge=7, le=3650),
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    """Archive completed task history without deleting audit evidence."""
    if user.role != Role.admin.value:
        raise HTTPException(status_code=403, detail="Admin role required")
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=older_than_days)
    archived = (
        db.query(Task)
        .filter(
            Task.organization_id == organization.id,
            Task.status.in_(("success", "failed", "degraded")),
            Task.created_at < cutoff,
        )
        .update({Task.status: "archived"}, synchronize_session=False)
    )
    db.commit()
    return {"archived": int(archived), "older_than_days": older_than_days}


@router.get("/tasks/{task_id}", response_model=TaskRead)
def get_task(
    task_id: str,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> Task:
    _mark_stale_source_sweeps(db, organization.id)
    task = db.scalar(
        select(Task).where(Task.id == task_id, Task.organization_id == organization.id)
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
