from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import IdPath, Pagination, get_current_user, pagination
from app.api.docs import error_responses
from app.db.session import get_db
from app.models import Booking, BookingStatus, User
from app.schemas.booking import BookingCreate, BookingOut
from app.schemas.common import Page
from app.services import booking_service

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.post(
    "/",
    response_model=BookingOut,
    status_code=201,
    summary="Book a diagnostic test",
    description="The amount is looked up from the centre's price list and stored on the booking; "
    "the client cannot set it. The booking starts as `PENDING` until it is paid.",
    responses=error_responses(400, 401, 404, 422),
)
def create_booking(
    payload: BookingCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Booking:
    return booking_service.create_booking(
        db, user, payload.centre_id, payload.test_id, payload.appointment_datetime
    )


@router.get(
    "/",
    response_model=Page[BookingOut],
    summary="List my bookings (newest first)",
    responses=error_responses(401, 422),
)
def list_bookings(
    status: BookingStatus | None = Query(None, description="Only bookings in this status"),
    page: Pagination = Depends(pagination),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[BookingOut]:
    items, total = booking_service.list_bookings(db, user, page.limit, page.offset, status)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.get(
    "/{booking_id}",
    response_model=BookingOut,
    summary="Get one of my bookings",
    description="Another user's booking returns 404 (not 403) so booking ids cannot be probed.",
    responses=error_responses(401, 404, 422),
)
def get_booking(booking_id: IdPath, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Booking:
    return booking_service.get_booking(db, user, booking_id)


@router.post(
    "/{booking_id}/cancel",
    response_model=BookingOut,
    summary="Cancel a booking",
    description="Allowed while the booking is `PENDING` or `FAILED`. A `CONFIRMED` or already `CANCELLED` booking returns 409.",
    responses=error_responses(401, 404, 409, 422),
)
def cancel_booking(booking_id: IdPath, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Booking:
    return booking_service.cancel_booking(db, user, booking_id)
