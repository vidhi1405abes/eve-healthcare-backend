from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import WebhookOutcome


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    __table_args__ = (CheckConstraint("status IN ('SUCCESS', 'FAILED')", name="status_valid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"), index=True)
    status: Mapped[str] = mapped_column(String(16))
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[WebhookOutcome | None] = mapped_column(Enum(WebhookOutcome, name="webhook_outcome"))
    detail: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
