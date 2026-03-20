from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, model_validator, ConfigDict
from app.models.notification import (
    NotificationChannel,
    NotificationPriority,
    NotificationStatus,
    SourceService,
    EventType,
    NotificationErrorCode,
)


def int_to_label(enum_class, value):
    try:
        return enum_class(value).name.lower()
    except Exception:
        return str(value)


class NotificationChannelStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel: str
    status: str
    ctime: datetime

    @model_validator(mode="before")
    @classmethod
    def convert(cls, data):
        if hasattr(data, "__dict__"):
            return {
                "id": data.id,
                "channel": int_to_label(NotificationChannel, data.channel),
                "status": int_to_label(NotificationStatus, data.status),
                "ctime": data.ctime,
            }
        return data


class NotificationCreatedResponse(BaseModel):
    idempotency_key: str
    event_type: str
    notifications: List[NotificationChannelStatus]


class NotificationDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    idempotency_key: str
    source_service: str
    event_type: str
    channel: str
    recipient: str
    priority: str
    status: str
    error_code: Optional[str]
    retry_count: int
    next_retry_time: Optional[datetime]
    external_id: Optional[str]
    content: dict
    ctime: datetime
    mtime: Optional[datetime]
    stime: Optional[datetime]

    @model_validator(mode="before")
    @classmethod
    def convert(cls, data):
        if hasattr(data, "__dict__"):
            return {
                "id": data.id,
                "idempotency_key": data.idempotency_key,
                "source_service": int_to_label(SourceService, data.source_service),
                "event_type": int_to_label(EventType, data.event_type),
                "channel": int_to_label(NotificationChannel, data.channel),
                "recipient": data.recipient,
                "priority": int_to_label(NotificationPriority, data.priority),
                "status": int_to_label(NotificationStatus, data.status),
                "error_code": int_to_label(NotificationErrorCode, data.error_code) if data.error_code else None,
                "retry_count": data.retry_count,
                "next_retry_time": data.next_retry_time,
                "external_id": data.external_id,
                "content": data.content,
                "ctime": data.ctime,
                "mtime": data.mtime,
                "stime": data.stime,
            }
        return data


class NotificationListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_service: str
    event_type: str
    channel: str
    status: str
    priority: str
    recipient: str
    retry_count: int
    ctime: datetime
    stime: Optional[datetime]

    @model_validator(mode="before")
    @classmethod
    def convert(cls, data):
        if hasattr(data, "__dict__"):
            return {
                "id": data.id,
                "source_service": int_to_label(SourceService, data.source_service),
                "event_type": int_to_label(EventType, data.event_type),
                "channel": int_to_label(NotificationChannel, data.channel),
                "status": int_to_label(NotificationStatus, data.status),
                "priority": int_to_label(NotificationPriority, data.priority),
                "recipient": data.recipient,
                "retry_count": data.retry_count,
                "ctime": data.ctime,
                "stime": data.stime,
            }
        return data


class RetryResponse(BaseModel):
    id: int
    status: str
    retry_count: int
    message: str