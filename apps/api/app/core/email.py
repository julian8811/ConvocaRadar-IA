from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

import httpx

from app.core.config import get_settings


@dataclass(frozen=True)
class EmailDelivery:
    status: str
    dry_run: bool
    detail: str


def send_email(*, recipient: str, subject: str, message: str) -> EmailDelivery:
    settings = get_settings()
    if settings.resend_api_key:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": settings.resend_from,
                "to": [recipient],
                "subject": subject,
                "text": message,
            },
            timeout=20,
        )
        if response.is_error:
            raise RuntimeError(
                f"Resend rechazó el correo ({response.status_code}): {response.text[:300]}"
            )
        return EmailDelivery(status="sent", dry_run=False, detail="Email enviado mediante Resend.")
    if not settings.smtp_host:
        return EmailDelivery(
            status="sent",
            dry_run=True,
            detail="SMTP y Resend no están configurados; se registró una prueba local.",
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
    return EmailDelivery(status="sent", dry_run=False, detail="Email enviado mediante SMTP.")
