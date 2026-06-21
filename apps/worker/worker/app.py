from celery import Celery

from worker.config import get_settings

settings = get_settings()

celery_app = Celery(
    "convocaradar",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "worker.tasks.scrape_source",
        "worker.tasks.process_opportunity",
        "worker.tasks.generate_report",
        "worker.tasks.send_alerts",
        "worker.tasks.scheduler",
    ],
)

celery_app.conf.update(
    task_track_started=True,
    task_time_limit=300,
    worker_prefetch_multiplier=1,
    timezone="America/Bogota",
    beat_schedule={
        "run-enabled-sources-every-30-minutes": {
            "task": "run_enabled_sources",
            "schedule": 1800.0,
        },
        "send-due-alerts-every-5-minutes": {
            "task": "send_due_alerts",
            "schedule": 300.0,
        },
    },
)

import worker.tasks.generate_report  # noqa: E402,F401
import worker.tasks.process_opportunity  # noqa: E402,F401
import worker.tasks.scheduler  # noqa: E402,F401
import worker.tasks.scrape_source  # noqa: E402,F401
import worker.tasks.send_alerts  # noqa: E402,F401
