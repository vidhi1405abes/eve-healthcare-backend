import logging
import random
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ConflictError
from app.models import BookingStatus, Payment, PaymentStatus, User
from app.services import booking_service
from app.services.booking_state import change_status

logger = logging.getLogger("app.payment")


def create_payment(
    db: Session,
    user: User,
    booking_id: int,
    simulate_outcome: PaymentStatus | None,
    idempotency_key: str | None,
) -> tuple[Payment, bool]:
    booking = booking_service.get_booking(db, user, booking_id, for_update=True)

    if idempotency_key:
        existing = _find_by_key(db, user.id, idempotency_key)
        if existing is not None:
            return _replay(existing, booking_id), True

    if booking.status not in (BookingStatus.PENDING, BookingStatus.FAILED):
        raise ConflictError(f"Booking is {booking.status.value} and cannot be paid", code="booking_not_payable")
    if db.scalar(select(Payment.id).where(Payment.booking_id == booking.id, Payment.status == PaymentStatus.PENDING)):
        raise ConflictError("A payment for this booking is already in progress", code="payment_in_progress")

    if booking.status == BookingStatus.FAILED:
        change_status(booking, BookingStatus.PENDING, reason="payment_retry")

    outcome = simulate_outcome or _random_outcome()
    payment = Payment(
        booking_id=booking.id,
        user_id=user.id,
        amount=booking.amount,
        status=outcome,
        provider_reference=f"pay_{uuid.uuid4().hex}",
        idempotency_key=idempotency_key,
    )
    db.add(payment)
    if outcome == PaymentStatus.SUCCESS:
        change_status(booking, BookingStatus.CONFIRMED, reason="payment_succeeded")
    elif outcome == PaymentStatus.FAILED:
        change_status(booking, BookingStatus.FAILED, reason="payment_failed")

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _find_by_key(db, user.id, idempotency_key) if idempotency_key else None
        if existing is None:
            raise
        return _replay(existing, booking_id), True

    logger.info(
        "payment_created",
        extra={
            "payment_id": payment.id,
            "booking_id": booking_id,
            "status": payment.status.value,
            "provider_reference": payment.provider_reference,
        },
    )
    return payment, False


def _random_outcome() -> PaymentStatus:
    return PaymentStatus.SUCCESS if random.random() < settings.payment_success_rate else PaymentStatus.FAILED


def _find_by_key(db: Session, user_id: int, key: str) -> Payment | None:
    return db.scalar(select(Payment).where(Payment.user_id == user_id, Payment.idempotency_key == key))


def _replay(existing: Payment, booking_id: int) -> Payment:
    if existing.booking_id != booking_id:
        raise ConflictError(
            "This Idempotency-Key was already used for a different booking", code="idempotency_key_reused"
        )
    return existing
