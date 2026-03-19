import uuid
from enum import Enum

from sqlalchemy import Column, DateTime, Integer, String, Text, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.database import Base


class NotificationStatus(int, Enum):
    PENDING  = 1
    QUEUED   = 2
    SENT     = 3
    FAILED   = 4
    RETRYING = 5


class NotificationChannel(int, Enum):
    EMAIL = 1
    SMS   = 2
    PUSH  = 3


class NotificationPriority(int, Enum):
    CRITICAL = 1   # OTP, security alerts
    HIGH     = 2   # order confirmation, payment receipt
    MEDIUM   = 3   # shipping updates
    LOW      = 4   # marketing, newsletters


class SourceService(int, Enum):
    ORDER    = 1
    PAYMENT  = 2
    SHIPPING = 3


class Notification(Base):
    __tablename__ = "notifications"

    # identity
    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    idempotency_key = Column(String(255), nullable=False)

    # where it came from — stored as integer
    source_service  = Column(Integer, nullable=False)  # SourceService enum
    event_type      = Column(String(100), nullable=False)

    # where it goes — stored as integer
    channel         = Column(Integer, nullable=False)  # NotificationChannel enum
    recipient       = Column(String(255), nullable=False)
    subject         = Column(String(500))
    body            = Column(Text, nullable=False)

    # priority and state — stored as integers
    priority        = Column(Integer, default=NotificationPriority.MEDIUM, nullable=False)
    status          = Column(Integer, default=NotificationStatus.PENDING, nullable=False)

    # retry tracking
    retry_count     = Column(Integer, default=0)
    max_retries     = Column(Integer, default=3)
    next_retry_at   = Column(DateTime(timezone=True))
    error_message   = Column(Text)

    # provider response
    external_id     = Column(String(255))

    # flexible metadata — no fixed schema needed
    metadata_       = Column("metadata", JSONB, default=dict)

    # timestamps
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), onupdate=func.now())
    sent_at         = Column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_notifications_idempotency_key"),
        Index("ix_notifications_worker", "status", "priority", "next_retry_at"),
    )

    def __repr__(self):
        return (
            f"<Notification id={self.id} "
            f"channel={NotificationChannel(self.channel).name} "
            f"status={NotificationStatus(self.status).name} "
            f"priority={NotificationPriority(self.priority).name}>"
        )