from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, computed_field, Field

from app.models.notification import (
    NotificationChannel,
    NotificationPriority,
    NotificationStatus,
    SourceService,
)


class NotificationResponse(BaseModel):
    """
    Returned after POST /notifications
    Minimal — just enough to confirm creation and track later
    """
    id: UUID
    idempotency_key: str
    source_service: int
    event_type: str
    channel: int
    recipient: str
    status: int
    priority: int
    created_at: datetime

    @computed_field
    @property
    def channel_label(self) -> str:
        return NotificationChannel(self.channel).name.lower()

    @computed_field
    @property
    def status_label(self) -> str:
        return NotificationStatus(self.status).name.lower()

    @computed_field
    @property
    def source_service_label(self) -> str:
        return SourceService(self.source_service).name.lower()

    @computed_field
    @property
    def priority_label(self) -> str:
        return NotificationPriority(self.priority).name.lower()

    class Config:
        from_attributes = True


class NotificationDetailResponse(BaseModel):
    """
    Returned after GET /notifications/{id}
    Full details including retry info, error, timestamps
    """
    id: UUID
    idempotency_key: str
    source_service: int
    event_type: str
    channel: int
    recipient: str
    subject: Optional[str]
    status: int
    priority: int
    retry_count: int
    max_retries: int
    external_id: Optional[str]
    error_message: Optional[str]
    extra_data: Optional[dict] = Field(None, alias="metadata_")
    created_at: datetime
    updated_at: Optional[datetime]
    sent_at: Optional[datetime]
    next_retry_at: Optional[datetime]

    @computed_field
    @property
    def channel_label(self) -> str:
        return NotificationChannel(self.channel).name.lower()

    @computed_field
    @property
    def status_label(self) -> str:
        return NotificationStatus(self.status).name.lower()

    @computed_field
    @property
    def source_service_label(self) -> str:
        return SourceService(self.source_service).name.lower()

    @computed_field
    @property
    def priority_label(self) -> str:
        return NotificationPriority(self.priority).name.lower()

    class Config:
        from_attributes = True
        populate_by_name = True