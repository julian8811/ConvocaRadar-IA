"""Audit logging and source health alert functions.

Extracted from ``_legacy.py`` (PR C-2b). Provides audit trail logging,
source health status determination, and source health alert creation.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Alert, AuditLog, Role, Source, SourceRun, User


def audit(
    db: Session,
    action: str,
    resource_type: str,
    user: User | None,
    resource_id: str | None = None,
) -> None:
    db.add(
        AuditLog(
            organization_id=user.organization_id if user else None,
            user_id=user.id if user else None,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
        )
    )


def _source_health_status(recent_runs: list[SourceRun]) -> str:
    failures = sum(1 for run in recent_runs if run.status == "failed")
    if not recent_runs:
        return "idle"
    if recent_runs[0].status == "failed" or failures >= 3:
        return "failing"
    if failures > 0:
        return "degraded"
    return "healthy"


def create_source_health_alert(
    db: Session,
    source: Source,
    *,
    reason: str,
    recipient_email: str | None = None,
) -> Alert | None:
    if not source.organization_id:
        return None
    recipient = recipient_email
    if not recipient:
        recipient = db.scalar(
            select(User.email)
            .where(
                User.organization_id == source.organization_id,
                User.role == Role.admin.value,
            )
            .order_by(User.created_at.asc())
        )
    if not recipient:
        return None
    subject = f"Fuente en observacion: {source.name}"
    existing = db.scalar(
        select(Alert).where(
            Alert.organization_id == source.organization_id,
            Alert.alert_type == "source_health",
            Alert.recipient == recipient,
            Alert.subject == subject,
            Alert.status.in_(["pending", "sent", "paused"]),
        )
    )
    if existing:
        return None
    alert = Alert(
        organization_id=source.organization_id,
        opportunity_id=None,
        alert_type="source_health",
        channel="email",
        recipient=recipient,
        subject=subject,
        message=(
            f"La fuente '{source.name}' ({source.key}) muestra problemas: {reason}. "
            "Revisar selector, credenciales, endpoint o disponibilidad."
        ),
        status="pending",
    )
    db.add(alert)
    return alert
