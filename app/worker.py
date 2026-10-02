from celery import Celery

from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.services import maintenance_service, webhook_failure_service

celery_app = Celery("eve_healthcare", broker=settings.redis_url or "redis://localhost:6379/0")
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    broker_connection_timeout=2,
    broker_connection_retry_on_startup=True,
    worker_hijack_root_logger=False,
    beat_schedule={
        "expire-stale-pending-payments": {
            "task": "app.worker.expire_stale_payments",
            "schedule": 300.0,
        }
    },
)
configure_logging(settings.log_level)


@celery_app.task(bind=True, name="app.worker.retry_webhook", max_retries=settings.webhook_retry_max_attempts)
def retry_webhook(self, failure_id: int) -> None:
    with SessionLocal() as db:
        finished = webhook_failure_service.retry_failure(db, failure_id)
    if not finished:
        raise self.retry(countdown=settings.webhook_retry_base_seconds * 2**self.request.retries)


@celery_app.task(name="app.worker.expire_stale_payments")
def expire_stale_payments() -> int:
    with SessionLocal() as db:
        return maintenance_service.expire_stale_pending_payments(db)
