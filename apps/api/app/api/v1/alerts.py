from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_organization, get_current_user
from app.core.email import send_email
from app.core.config import get_settings
from app.db.session import get_db
from app.models import Alert, Opportunity, OpportunityScore, OpportunityStatus, Organization, Priority, User
from app.schemas import AlertCreate, AlertRead, AlertTestRequest, AlertUpdate
from app.services import audit

router = APIRouter()


def send_pending_alerts(db: Session) -> int:
    """Send all pending alerts that haven't been sent yet.

    Called by the periodic scheduler. Returns the number of alerts sent.
    Uses Resend API when configured, falls back to dry-run logging.
    """
    import structlog
    logger = structlog.get_logger(__name__)
    pending = list(
        db.scalars(
            select(Alert).where(Alert.status == "pending").order_by(Alert.created_at.asc()).limit(50)
        )
    )
    if not pending:
        return 0
    sent = 0
    for alert in pending:
        try:
            send_email(recipient=alert.recipient, subject=alert.subject, message=alert.message)
            alert.status = "sent"
            alert.sent_at = datetime.now(UTC).replace(tzinfo=None)
            sent += 1
        except Exception as exc:
            logger.warning("alert_send_failed", alert_id=alert.id, error=str(exc))
            alert.status = "failed"
    db.flush()
    logger.info("pending_alerts_sent", sent=sent, total=len(pending))
    return sent


def _send_alert(alert: Alert) -> None:
    if alert.channel != "email":
        raise HTTPException(status_code=400, detail="Only email alerts can be sent in the MVP")
    try:
        send_email(recipient=alert.recipient, subject=alert.subject, message=alert.message)
    except Exception as exc:
        alert.status = "failed"
        alert.sent_at = None
        raise HTTPException(status_code=502, detail=f"Email delivery failed: {exc}") from exc
    alert.status = "sent"
    alert.sent_at = datetime.now(UTC).replace(tzinfo=None)


@router.get("/alerts/count")
def count_pending_alerts(
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    """Return count of pending alerts for the current org (in-app badge)."""
    total = db.scalar(
        select(func.count(Alert.id)).where(
            Alert.organization_id == organization.id,
            Alert.status == "pending",
        )
    ) or 0
    return {"pending": total}


@router.get("/alerts", response_model=list[AlertRead])
def list_alerts(
    faculty: str | None = None,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> list[Alert]:
    stmt = select(Alert).where(Alert.organization_id == organization.id)
    if faculty:
        from app.models import Faculty
        fac = db.scalar(select(Faculty).where((Faculty.key == faculty) | (Faculty.slug == faculty) | (Faculty.id == faculty)))
        if fac:
            stmt = stmt.where(Alert.faculty_id == fac.id)
        else:
            return []
    return list(db.scalars(stmt.order_by(Alert.created_at.desc())))


@router.delete("/alerts")
def bulk_delete_alerts(
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    import structlog
    logger = structlog.get_logger(__name__)
    count = db.scalar(select(func.count(Alert.id)).where(Alert.organization_id == organization.id)) or 0
    # Delete all alerts for org
    alerts = list(db.scalars(select(Alert).where(Alert.organization_id == organization.id)))
    for a in alerts:
        db.delete(a)
    db.flush()
    audit(db, "bulk_delete_alerts", "alert", user, None, metadata={"deleted_count": int(count)})
    db.commit()
    logger.info("bulk_delete_alerts", organization_id=organization.id, deleted_count=count)
    return {"deleted_count": count}


@router.post("/alerts", response_model=AlertRead)
def create_alert(
    payload: AlertCreate,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Alert:
    alert = Alert(**payload.model_dump(), organization_id=organization.id)
    db.add(alert)
    db.flush()
    audit(db, "create_alert", "alert", user, alert.id)
    db.commit()
    db.refresh(alert)
    return alert


@router.patch("/alerts/{alert_id}", response_model=AlertRead)
def update_alert(
    alert_id: str,
    payload: AlertUpdate,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Alert:
    alert = db.scalar(select(Alert).where(Alert.id == alert_id, Alert.organization_id == organization.id))
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    previous_status = alert.status
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(alert, key, value)

    if alert.status == "sent" and previous_status != "sent":
        alert.sent_at = datetime.now(UTC).replace(tzinfo=None)
    if alert.status != "sent":
        alert.sent_at = None

    audit(db, "update_alert", "alert", user, alert.id)
    db.commit()
    db.refresh(alert)
    return alert


@router.post("/alerts/generate", response_model=list[AlertRead])
def generate_recommended_alerts(
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Alert]:
    candidates: list[Alert] = []
    recipient = get_settings().alert_default_recipient or user.email

    closing_opportunities = db.scalars(
        select(Opportunity).where(
            ((Opportunity.organization_id == organization.id) | (Opportunity.organization_id.is_(None))),
            Opportunity.status == OpportunityStatus.closing_soon.value,
        )
    )
    for opportunity in closing_opportunities:
        exists = db.scalar(
            select(Alert).where(
                Alert.organization_id == organization.id,
                Alert.opportunity_id == opportunity.id,
                Alert.alert_type == "closing_soon",
                Alert.recipient == recipient,
            )
        )
        if exists:
            continue
        candidates.append(
            Alert(
                organization_id=organization.id,
                opportunity_id=opportunity.id,
                alert_type="closing_soon",
                channel="email",
                recipient=recipient,
                subject=f"Cierre próximo: {opportunity.title}",
                message=(
                    f"La convocatoria '{opportunity.title}' cierra "
                    f"{opportunity.close_date.date().isoformat() if opportunity.close_date else 'pronto'}."
                ),
            )
        )

    high_scores = db.execute(
        select(Opportunity, OpportunityScore)
        .join(OpportunityScore, OpportunityScore.opportunity_id == Opportunity.id)
        .where(
            ((Opportunity.organization_id == organization.id) | (Opportunity.organization_id.is_(None))),
            OpportunityScore.organization_id == organization.id,
            OpportunityScore.priority == Priority.high.value,
        )
    )
    for opportunity, score in high_scores:
        exists = db.scalar(
            select(Alert).where(
                Alert.organization_id == organization.id,
                Alert.opportunity_id == opportunity.id,
                Alert.alert_type == "high_compatibility",
                Alert.recipient == recipient,
            )
        )
        if exists:
            continue
        candidates.append(
            Alert(
                organization_id=organization.id,
                opportunity_id=opportunity.id,
                alert_type="high_compatibility",
                channel="email",
                recipient=recipient,
                subject=f"Alta compatibilidad ({int(score.score)}): {opportunity.title}",
                message=f"La convocatoria '{opportunity.title}' tiene prioridad alta para {organization.name}.",
            )
        )

    for alert in candidates:
        db.add(alert)
        db.flush()
        audit(db, "generate_alert", "alert", user, alert.id)
    db.commit()
    return candidates


@router.post("/alerts/{alert_id}/send", response_model=AlertRead)
def send_alert(
    alert_id: str,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Alert:
    alert = db.scalar(select(Alert).where(Alert.id == alert_id, Alert.organization_id == organization.id))
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    if alert.status == "paused":
        raise HTTPException(status_code=400, detail="Paused alerts cannot be sent")
    try:
        _send_alert(alert)
    finally:
        audit(db, "send_alert", "alert", user, alert.id)
        db.commit()
    db.refresh(alert)
    return alert


@router.delete("/alerts/{alert_id}", status_code=204)
def delete_alert(
    alert_id: str,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    alert = db.scalar(select(Alert).where(Alert.id == alert_id, Alert.organization_id == organization.id))
    if alert:
        audit(db, "delete_alert", "alert", user, alert.id)
        db.delete(alert)
        db.commit()


@router.post("/alerts/test", response_model=AlertRead)
def test_alert(
    payload: AlertTestRequest,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Alert:
    alert = Alert(
        organization_id=organization.id,
        alert_type="test",
        channel="email",
        recipient=str(payload.recipient),
        subject="Prueba de alerta del Observatorio de Convocatorias Institucional",
        message="Esta es una alerta de prueba del Observatorio de Convocatorias Institucional.",
        status="pending",
    )
    db.add(alert)
    db.flush()
    try:
        _send_alert(alert)
    finally:
        audit(db, "test_alert", "alert", user, alert.id)
        db.commit()
    db.refresh(alert)
    return alert


