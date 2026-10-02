from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class WebhookPayload(BaseModel):
    event_id: str = Field(min_length=1, max_length=128, description="Unique id of this event, used for de-duplication")
    provider_reference: str = Field(min_length=1, max_length=64, description="The `provider_reference` of a payment")
    status: Literal["SUCCESS", "FAILED"]
    timestamp: AwareDatetime = Field(description="When the provider produced the event (must include a timezone)")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "event_id": "evt_1001",
                    "provider_reference": "pay_0123456789abcdef0123456789abcdef",
                    "status": "SUCCESS",
                    "timestamp": "2030-01-15T09:30:00+00:00",
                }
            ]
        }
    )


class WebhookResponse(BaseModel):
    status: Literal["processed", "ignored", "already_processed"]
    detail: str | None = None
