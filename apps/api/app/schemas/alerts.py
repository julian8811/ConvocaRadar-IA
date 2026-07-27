"""Alert and audit-log Pydantic schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr


class AlertCreate(BaseModel):
    opportunity_id: str | None = None
    alert_type: str
    channel: str = "email"
    recipient: EmailStr
    subject: str
    message: str
    scheduled_at: datetime | None = None


class AlertUpdate(BaseModel):
    status: Literal["pending", "paused", "sent", "failed"] | None = None
    recipient: EmailStr | None = None
    subject: str | None = None
    message: str | None = None
    scheduled_at: datetime | None = None


class AlertTestRequest(BaseModel):
    recipient: EmailStr


class AlertRead(AlertCreate):
    id: str
    organization_id: str
    status: str
    sent_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogRead(BaseModel):
    id: str
    organization_id: str | None
    user_id: str | None
    action: str
    resource_type: str
    resource_id: str | None
    metadata_json: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}
