from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.docs import error_responses
from app.db.session import get_db
from app.models import Payment, User
from app.schemas.payment import PaymentCreate, PaymentOut
from app.services import payment_service

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post(
    "/",
    response_model=PaymentOut,
    status_code=201,
    summary="Pay for a booking (simulated)",
    description=(
        "Simulates a payment provider. SUCCESS -> booking `CONFIRMED`; FAILED -> booking `FAILED` "
        "(pay again to retry); PENDING -> waits for the webhook.\n\n"
        "Only the booking owner can pay, and only while the booking is `PENDING` or `FAILED`; "
        "a `CONFIRMED` or `CANCELLED` booking returns 409. The amount always comes from the booking.\n\n"
        "**Idempotency:** send an `Idempotency-Key` header. Repeating the request with the same key returns "
        "the original payment (header `Idempotent-Replayed: true`) instead of charging again. "
        "To retry after a FAILED payment use a *new* key."
    ),
    responses=error_responses(401, 404, 409, 422),
)
def create_payment(
    payload: PaymentCreate,
    response: Response,
    idempotency_key: str | None = Header(
        None, alias="Idempotency-Key", min_length=1, max_length=128, description="Unique per payment attempt"
    ),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Payment:
    payment, replayed = payment_service.create_payment(
        db, user, payload.booking_id, payload.simulate_outcome, idempotency_key
    )
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return payment
