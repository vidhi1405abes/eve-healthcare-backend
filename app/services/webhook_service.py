import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidStateTransition, NotFoundError
from app.models import Booking, BookingStatus, Payment, PaymentStatus, WebhookEvent, WebhookOutcome
from app.schemas.webhook import WebhookPayload
from app.services.booking_state import change_status

logger = logging.getLogger("app.webhook")

PG_UNIQUE_VIOLATION = "23505"


@dataclass
class WebhookResult:
    status: str
    detail: str | None = None


def process_webhook(db: Session, payload: WebhookPayload) -> WebhookResult:
    new_status = PaymentStatus(payload.status)

    payment = db.scalars(
        select(Payment)
        .where(Payment.provider_reference == payload.provider_reference)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).first()
    if payment is None:
        logger.warning(
            "webhook_unknown_payment",
            extra={"event_id": payload.event_id, "provider_reference": payload.provider_reference},
        )
        raise NotFoundError("No payment with this provider_reference", code="payment_not_found")

    event = WebhookEvent(
        event_id=payload.event_id,
        payment_id=payment.id,
        status=payload.status,
        event_timestamp=payload.timestamp,
    )
    db.add(event)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if getattr(exc.orig, "pgcode", None) != PG_UNIQUE_VIOLATION:
            raise
        logger.info("webhook_duplicate", extra={"event_id": payload.event_id})
        return WebhookResult("already_processed")

    booking = db.scalars(
        select(Booking)
        .where(Booking.id == payment.booking_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()

    outcome, detail = _apply_event(payment, booking, new_status)
    event.outcome = outcome
    event.detail = detail
    db.commit()

    log = logger.info if outcome == WebhookOutcome.APPLIED else logger.warning
    log(
        "webhook_processed" if outcome == WebhookOutcome.APPLIED else "webhook_ignored",
        extra={
            "event_id": payload.event_id,
            "payment_id": payment.id,
            "booking_id": booking.id,
            "event_status": payload.status,
            "outcome": outcome.value,
            "detail": detail,
        },
    )
    return WebhookResult("processed" if outcome == WebhookOutcome.APPLIED else "ignored", detail)


def _apply_event(payment: Payment, booking: Booking, new_status: PaymentStatus) -> tuple[WebhookOutcome, str]:
    if payment.status == new_status:
        return WebhookOutcome.IGNORED, f"payment is already {payment.status.value}; nothing to do"

    if payment.status != PaymentStatus.PENDING:
        return WebhookOutcome.IGNORED, f"payment is already {payment.status.value}; cannot become {new_status.value}"

    target = BookingStatus.CONFIRMED if new_status == PaymentStatus.SUCCESS else BookingStatus.FAILED
    try:
        change_status(booking, target, reason="webhook")
    except InvalidStateTransition:
        return WebhookOutcome.IGNORED, f"booking is {booking.status.value}; cannot become {target.value}"

    payment.status = new_status
    return WebhookOutcome.APPLIED, f"payment {new_status.value}; booking {target.value}"
