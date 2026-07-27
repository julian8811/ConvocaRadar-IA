"""Report and task Pydantic schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ReportCreate(BaseModel):
    title: str = "Reporte ejecutivo de convocatorias"
    report_type: str = "custom"
    format: Literal["html", "pdf", "xlsx", "csv"] = "html"
    filters: dict[str, Any] = Field(default_factory=dict)


class ReportRead(BaseModel):
    id: str
    organization_id: str
    title: str
    report_type: str
    format: str
    status: str
    html_content: str
    file_path: str | None
    filters: dict[str, Any]
    generated_at: datetime

    model_config = {"from_attributes": True}


class TaskRead(BaseModel):
    id: str
    organization_id: str | None
    source_run_id: str | None
    task_type: str
    provider: str
    status: str
    external_id: str | None = None
    payload: dict[str, Any]
    result: dict[str, Any]
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
