from typing import Optional
from pydantic import BaseModel, field_validator
from app.models.notification import (
    NotificationChannel,
    NotificationPriority,
    SourceService,
)


class NotificationCreate(BaseModel):
    idempotency_key: str
    source_service: str        # "order" | "payment" | "shipping"
    event_type: str            # "order.created" | "payment.failed" etc
    channel: str               # "email" | "sms" | "push"
    recipient: str             # email / phone number / device token
    subject: Optional[str] = None   # email only
    body: str
    priority: int = NotificationPriority.MEDIUM
    metadata: Optional[dict] = {}

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v):
        allowed = {c.name.lower() for c in NotificationChannel}
        if v.lower() not in allowed:
            raise ValueError(f"channel must be one of {allowed}")
        return v.lower()

    @field_validator("source_service")
    @classmethod
    def validate_source_service(cls, v):
        allowed = {s.name.lower() for s in SourceService}
        if v.lower() not in allowed:
            raise ValueError(f"source_service must be one of {allowed}")
        return v.lower()

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v):
        valid = {p.value for p in NotificationPriority}
        if v not in valid:
            raise ValueError(f"priority must be one of {valid}")
        return v

    def channel_as_int(self) -> int:
        return NotificationChannel[self.channel.upper()].value

    def source_service_as_int(self) -> int:
        return SourceService[self.source_service.upper()].value