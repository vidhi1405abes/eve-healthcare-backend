import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestError, NotFoundError
from app.models import Booking, BookingStatus, CentreTest, User
from app.services import catalog_service
from app.services.booking_state import change_status

logger = logging.getLogger("app.booking")


def create_booking(
    db: Session, user: User, centre_id: int, test_id: int, appointment_datetime: datetime
) -> Booking:
    catalog_service.get_centre(db, centre_id)
    catalog_service.get_test(db, test_id)

    offering = db.scalar(select(CentreTest).where(CentreTest.centre_id == centre_id, CentreTest.test_id == test_id))
    if offering is None:
        raise BadRequestError("This centre does not offer the selected test", code="test_not_offered")
    if appointment_datetime <= datetime.now(timezone.utc):
        raise BadRequestError("Appointment must be in the future", code="appointment_in_past")

    booking = Booking(
        user_id=user.id,
        centre_id=centre_id,
        test_id=test_id,
        appointment_datetime=appointment_datetime,
        amount=offering.price,
        status=BookingStatus.PENDING,
    )
    db.add(booking)
    db.commit()
    logger.info("booking_created", extra={"booking_id": booking.id, "user_id": user.id, "amount": str(booking.amount)})
    return booking


def list_bookings(
    db: Session, user: User, limit: int, offset: int, status: BookingStatus | None
) -> tuple[list[Booking], int]:
    stmt = select(Booking).where(Booking.user_id == user.id)
    if status is not None:
        stmt = stmt.where(Booking.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(Booking.id.desc()).limit(limit).offset(offset)).all()
    return list(items), total


def get_booking(db: Session, user: User, booking_id: int, for_update: bool = False) -> Booking:
    stmt = select(Booking).where(Booking.id == booking_id, Booking.user_id == user.id)
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    booking = db.scalars(stmt).first()
    if booking is None:
        raise NotFoundError("Booking not found", code="booking_not_found")
    return booking


def cancel_booking(db: Session, user: User, booking_id: int) -> Booking:
    booking = get_booking(db, user, booking_id, for_update=True)
    change_status(booking, BookingStatus.CANCELLED, reason="cancelled_by_user")
    db.commit()
    return booking
