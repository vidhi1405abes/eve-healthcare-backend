import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import WebhookFailure
from app.schemas.webhook import WebhookPayload
from app.services import webhook_service

logger = logging.getLogger("app.webhook")


def record_failure(payload: WebhookPayload, reason: str, error: str | None) -> tuple[int, bool]:
    with SessionLocal() as db:
        existing = db.scalar(
            select(WebhookFailure).where(
                WebhookFailure.event_id == payload.event_id, WebhookFailure.resolved_at.is_(None)
            )
        )
        if existing is not None:
            return existing.id, False
        failure = WebhookFailure(
            event_id=payload.event_id,
            provider_reference=payload.provider_reference,
            status=payload.status,
            event_timestamp=payload.timestamp,
            reason=reason,
            error=error,
        )
        db.add(failure)
        db.commit()
        logger.warning(
            "webhook_failure_recorded",
            extra={"failure_id": failure.id, "event_id": payload.event_id, "reason": reason},
        )
        return failure.id, True


def schedule_retry(failure_id: int) -> None:
    from app.worker import retry_webhook

    try:
        retry_webhook.apply_async(args=[failure_id], countdown=settings.webhook_retry_base_seconds)
    except Exception:
        logger.warning("webhook_retry_not_scheduled", extra={"failure_id": failure_id}, exc_info=True)


def keep_for_retry(payload: WebhookPayload, reason: str, error: str | None) -> None:
    try:
        failure_id, created = record_failure(payload, reason, error)
        if created:
            schedule_retry(failure_id)
    except Exception:
        logger.exception("webhook_failure_not_recorded", extra={"event_id": payload.event_id})


def retry_failure(db: Session, failure_id: int) -> bool:
    failure = db.get(WebhookFailure, failure_id)
    if failure is None or failure.resolved_at is not None:
        return True

    payload = WebhookPayload(
        event_id=failure.event_id,
        provider_reference=failure.provider_reference,
        status=failure.status,
        timestamp=failure.event_timestamp,
    )
    try:
        result = webhook_service.process_webhook(db, payload)
    except Exception as exc:
        db.rollback()
        failure = db.get(WebhookFailure, failure_id)
        failure.attempts += 1
        failure.last_attempt_at = datetime.now(timezone.utc)
        failure.error = repr(exc)[:500]
        db.commit()
        logger.warning(
            "webhook_retry_failed", extra={"failure_id": failure_id, "attempts": failure.attempts}
        )
        return False

    failure = db.get(WebhookFailure, failure_id)
    failure.attempts += 1
    failure.last_attempt_at = failure.resolved_at = datetime.now(timezone.utc)
    db.commit()
    logger.info(
        "webhook_retry_succeeded",
        extra={"failure_id": failure_id, "attempts": failure.attempts, "result": result.status},
    )
    return True
