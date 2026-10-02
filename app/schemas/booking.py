from datetime import datetime
from decimal import Decimal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from app.models import BookingStatus
from app.schemas.common import PositiveId


class BookingCreate(BaseModel):
    centre_id: PositiveId
    test_id: PositiveId
    appointment_datetime: AwareDatetime

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"centre_id": 1, "test_id": 1, "appointment_datetime": "2030-01-15T09:30:00+00:00"}]
        }
    )


class BookingOut(BaseModel):
    id: int
    user_id: int
    test_id: int
    centre_id: int
    appointment_datetime: datetime
    amount: Decimal
    status: BookingStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
