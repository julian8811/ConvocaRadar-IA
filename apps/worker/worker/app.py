import ssl

from celery import Celery

from worker.config import get_settings

settings = get_settings()
redis_ssl_options = {"ssl_cert_reqs": ssl.CERT_NONE} if settings.redis_url.startswith("rediss://") else None

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
        "worker.tasks.bootstrap",
        "worker.tasks.health",
    ],
)

celery_config = {
    "task_track_started": True,
    "task_time_limit": 300,
    "worker_prefetch_multiplier": 1,
    "timezone": "America/Bogota",
    "beat_schedule": {
        "run-enabled-sources-every-30-minutes": {
            "task": "run_enabled_sources",
            "schedule": 1800.0,
        },
        "send-due-alerts-every-5-minutes": {
            "task": "send_due_alerts",
            "schedule": 300.0,
        },
    },
}
if redis_ssl_options:
    celery_config["broker_use_ssl"] = redis_ssl_options
    celery_config["redis_backend_use_ssl"] = redis_ssl_options

celery_app.conf.update(**celery_config)

import worker.tasks.generate_report  # noqa: E402,F401
import worker.tasks.process_opportunity  # noqa: E402,F401
import worker.tasks.scheduler  # noqa: E402,F401
import worker.tasks.scrape_source  # noqa: E402,F401
import worker.tasks.send_alerts  # noqa: E402,F401
import worker.tasks.bootstrap  # noqa: E402,F401
