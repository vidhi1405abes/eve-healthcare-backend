from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models import PaymentStatus
from app.schemas.common import PositiveId


class PaymentCreate(BaseModel):
    booking_id: PositiveId
    simulate_outcome: PaymentStatus | None = Field(
        default=None,
        description="Force the simulated provider's result: SUCCESS, FAILED, or PENDING "
        "(provider accepted the payment and will confirm later via the webhook). "
        "If omitted the outcome is random (see PAYMENT_SUCCESS_RATE).",
    )

    model_config = ConfigDict(json_schema_extra={"examples": [{"booking_id": 1, "simulate_outcome": "SUCCESS"}]})


class PaymentOut(BaseModel):
    id: int
    booking_id: int
    amount: Decimal
    status: PaymentStatus
    provider_reference: str
    idempotency_key: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
