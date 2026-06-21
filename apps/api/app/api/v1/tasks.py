from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_organization
from app.db.session import get_db
from app.models import Organization, Task
from app.schemas import TaskRead

router = APIRouter()


@router.get("/tasks", response_model=list[TaskRead])
def list_tasks(
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> list[Task]:
    return list(
        db.scalars(
            select(Task)
            .where(Task.organization_id == organization.id)
            .order_by(Task.created_at.desc())
            .limit(100)
        )
    )


@router.get("/tasks/{task_id}", response_model=TaskRead)
def get_task(
    task_id: str,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> Task:
    task = db.scalar(select(Task).where(Task.id == task_id, Task.organization_id == organization.id))
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
