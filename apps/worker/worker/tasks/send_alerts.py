from datetime import datetime

from worker.app import celery_app


@celery_app.task(name="send_alert")
def send_alert(recipient: str, subject: str, message: str) -> dict[str, str]:
    return {
        "recipient": recipient,
        "subject": subject,
        "status": "sent_local",
        "sent_at": datetime.utcnow().isoformat(),
        "message": message,
    }
