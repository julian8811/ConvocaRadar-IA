from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from app.core.config import get_settings


@dataclass(frozen=True)
class EmailDelivery:
    status: str
    dry_run: bool
    detail: str


def send_email(*, recipient: str, subject: str, message: str) -> EmailDelivery:
    settings = get_settings()
    if not settings.smtp_host:
        return EmailDelivery(
            status="sent",
            dry_run=True,
            detail="SMTP is not configured; delivery was recorded as a development dry run.",
        )

    email = EmailMessage()
    email["From"] = settings.smtp_from
    email["To"] = recipient
    email["Subject"] = subject
    email.set_content(message)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(email)

    return EmailDelivery(status="sent", dry_run=False, detail="Email delivered through SMTP.")
