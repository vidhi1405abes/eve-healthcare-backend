import logging

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.docs import error_responses
from app.core.exceptions import InvalidPayloadError, UnauthorizedError
from app.core.security import verify_webhook_signature
from app.db.session import get_db
from app.models import Payment, User
from app.schemas.payment import PaymentCreate, PaymentOut
from app.schemas.webhook import WebhookPayload, WebhookResponse
from app.services import payment_service, webhook_service

logger = logging.getLogger("app.webhook")
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


WEBHOOK_REQUEST_BODY = {
    "required": True,
    "content": {
        "application/json": {
            "schema": WebhookPayload.model_json_schema(),
            "example": WebhookPayload.model_config["json_schema_extra"]["examples"][0],
        }
    },
}


async def read_raw_body(request: Request) -> bytes:
    return await request.body()


@router.post(
    "/webhook/",
    response_model=WebhookResponse,
    response_model_exclude_none=True,
    summary="Payment provider webhook (idempotent, signed)",
    description=(
        "Called by the simulated payment provider. Send the header `X-Signature: <hex HMAC-SHA256 of the raw body "
        "using WEBHOOK_SECRET>` (generate one with `python -m scripts.sign_webhook`).\n\n"
        "* Same `event_id` delivered again -> `200 {\"status\": \"already_processed\"}`, nothing changes.\n"
        "* Event that conflicts with the current state (e.g. late FAILED after SUCCESS) -> `200` `ignored`.\n"
        "* Always 2xx for events we have seen, so the provider can retry safely.\n"
        "* Missing/invalid signature -> 401. Unknown `provider_reference` -> 404. Invalid body -> 422."
    ),
    openapi_extra={"requestBody": WEBHOOK_REQUEST_BODY},
    responses=error_responses(401, 404, 422),
)
def payment_webhook(
    body: bytes = Depends(read_raw_body),
    x_signature: str | None = Header(None, alias="X-Signature", description="Hex HMAC-SHA256 of the raw request body"),
    db: Session = Depends(get_db),
) -> WebhookResponse:
    if not verify_webhook_signature(body, x_signature):
        logger.warning("webhook_invalid_signature", extra={"has_signature": bool(x_signature)})
        raise UnauthorizedError("Missing or invalid webhook signature", code="invalid_signature")

    try:
        payload = WebhookPayload.model_validate_json(body)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        raise InvalidPayloadError(f"Invalid webhook payload ({problems})")

    result = webhook_service.process_webhook(db, payload)
    return WebhookResponse(status=result.status, detail=result.detail)
