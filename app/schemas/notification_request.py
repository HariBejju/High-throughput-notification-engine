from typing import Optional
from pydantic import BaseModel, field_validator, model_validator
from app.models.notification import (
    NotificationPriority,
    SourceService,
    EventType,
    NotificationChannel,
)
from app.event_channel_map import EVENT_CHANNEL_MAP, CHANNEL_RECIPIENT_FIELD


class RecipientInfo(BaseModel):
    email:        Optional[str] = None
    phone:        Optional[str] = None
    device_token: Optional[str] = None


class NotificationCreate(BaseModel):
    idempotency_key: str
    source_service:  str          # "order" | "payment" | "shipping"
    event_type:      str          # "order_created" | "payment_failed" etc
    priority:        str = "medium"
    recipient:       RecipientInfo
    content:         dict         # per channel — email/sms/push keys

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

    @model_validator(mode="after")
    def validate_recipient_and_content(self):
        """
        Check that recipient has required fields for each channel
        the event type maps to, and content has per channel data.
        """
        event = EventType[self.event_type.upper()]
        channels = EVENT_CHANNEL_MAP.get(event, [])

        for channel in channels:
            # check recipient field
            field = CHANNEL_RECIPIENT_FIELD[channel]
            value = getattr(self.recipient, field, None)
            if not value:
                raise ValueError(
                    f"recipient.{field} is required for "
                    f"event_type={self.event_type} "
                    f"(channel={channel.name.lower()})"
                )

            # check content has channel key
            channel_name = channel.name.lower()
            if channel_name not in self.content:
                raise ValueError(
                    f"content.{channel_name} is required for "
                    f"event_type={self.event_type}"
                )

        return self

    # helpers
    def source_service_as_int(self) -> int:
        return SourceService[self.source_service.upper()].value

    def event_type_as_int(self) -> int:
        return EventType[self.event_type.upper()].value

    def priority_as_int(self) -> int:
        return NotificationPriority[self.priority.upper()].value