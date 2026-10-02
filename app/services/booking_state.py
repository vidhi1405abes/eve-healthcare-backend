import logging

from app.core.exceptions import InvalidStateTransition
from app.models import Booking, BookingStatus

logger = logging.getLogger("app.booking")

ALLOWED_TRANSITIONS: dict[BookingStatus, set[BookingStatus]] = {
    BookingStatus.PENDING: {BookingStatus.CONFIRMED, BookingStatus.FAILED, BookingStatus.CANCELLED},
    BookingStatus.FAILED: {BookingStatus.PENDING, BookingStatus.CANCELLED},
    BookingStatus.CONFIRMED: set(),
    BookingStatus.CANCELLED: set(),
}


def validate_transition(current: BookingStatus, target: BookingStatus) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidStateTransition(f"Cannot change booking status from {current.value} to {target.value}")


def change_status(booking: Booking, target: BookingStatus, reason: str) -> None:
    validate_transition(booking.status, target)
    previous = booking.status
    booking.status = target
    logger.info(
        "booking_status_changed",
        extra={
            "booking_id": booking.id,
            "from_status": previous.value,
            "to_status": target.value,
            "reason": reason,
        },
    )
