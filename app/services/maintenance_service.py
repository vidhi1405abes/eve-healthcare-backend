import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import InvalidStateTransition
from app.models import Booking, BookingStatus, Payment, PaymentStatus
from app.services.booking_state import change_status

logger = logging.getLogger("app.payment")


def expire_stale_pending_payments(db: Session, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=settings.payment_pending_timeout_minutes)
    stale_ids = db.scalars(
        select(Payment.id).where(Payment.status == PaymentStatus.PENDING, Payment.created_at < cutoff)
    ).all()

    expired = 0
    for payment_id in stale_ids:
        payment = db.scalars(
            select(Payment).where(Payment.id == payment_id).with_for_update().execution_options(populate_existing=True)
        ).one()
        if payment.status != PaymentStatus.PENDING:
            db.rollback()
            continue
        booking = db.scalars(
            select(Booking).where(Booking.id == payment.booking_id).with_for_update().execution_options(populate_existing=True)
        ).one()
        payment.status = PaymentStatus.FAILED
        try:
            change_status(booking, BookingStatus.FAILED, reason="payment_expired")
        except InvalidStateTransition:
            pass
        db.commit()
        expired += 1
        logger.warning("payment_expired", extra={"payment_id": payment_id, "booking_id": booking.id})
    return expired
