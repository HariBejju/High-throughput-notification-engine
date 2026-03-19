from typing import Optional
from pydantic import BaseModel, field_validator
from app.models.notification import (
    NotificationChannel,
    NotificationPriority,
    SourceService,
    EventType,
)


class NotificationCreate(BaseModel):
    idempotency_key: str
    source_service: str        # "order" | "payment" | "shipping"
    event_type: str            # "order_created" | "payment_failed" etc
    channel: str               # "email" | "sms" | "push"
    recipient: str
    priority: str = "medium"   # "critical" | "high" | "medium" | "low"
    content: dict              # channel specific content

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

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v):
        allowed = {e.name.lower() for e in EventType}
        if v.lower() not in allowed:
            raise ValueError(f"event_type must be one of {allowed}")
        return v.lower()

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v):
        allowed = {p.name.lower() for p in NotificationPriority}
        if v.lower() not in allowed:
            raise ValueError(f"priority must be one of {allowed}")
        return v.lower()

    # helpers to convert strings to integers for DB storage
    def channel_as_int(self) -> int:
        return NotificationChannel[self.channel.upper()].value

    def source_service_as_int(self) -> int:
        return SourceService[self.source_service.upper()].value

    def event_type_as_int(self) -> int:
        return EventType[self.event_type.upper()].value

    def priority_as_int(self) -> int:
        return NotificationPriority[self.priority.upper()].value