import uuid
from enum import Enum

from sqlalchemy import Column, DateTime, Integer, String, Text, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.database import Base


class NotificationStatus(str, Enum):
    PENDING  = "pending"
    QUEUED   = "queued"
    SENT     = "sent"
    FAILED   = "failed"
    RETRYING = "retrying"


class NotificationPriority(int, Enum):
    # lower number = higher priority
    CRITICAL = 1   # OTP, security alerts
    HIGH     = 2   # order confirmation, payment receipt
    MEDIUM   = 3   # shipping updates
    LOW      = 4   # marketing, newsletters


class Notification(Base):
    __tablename__ = "notifications"

    # identity
    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    idempotency_key = Column(String(255), nullable=False)

    # where it came from
    source_service  = Column(String(50), nullable=False)   # order | payment | shipping
    event_type      = Column(String(100), nullable=False)  # payment.confirmed etc

    # where it goes
    channel         = Column(String(20), nullable=False)   # email | sms | push
    recipient       = Column(String(255), nullable=False)  # email / phone / device token
    subject         = Column(String(500))                  # used by email only
    body            = Column(Text, nullable=False)

    # priority and state
    priority        = Column(Integer, default=NotificationPriority.MEDIUM)
    status          = Column(String(20), default=NotificationStatus.PENDING, nullable=False)

    # retry tracking
    retry_count     = Column(Integer, default=0)
    max_retries     = Column(Integer, default=3)
    next_retry_at   = Column(DateTime(timezone=True))
    error_message   = Column(Text)

    # provider response
    external_id     = Column(String(255))  # provider message ID for tracking

    # flexible metadata per event type — no fixed schema needed
    metadata_       = Column("metadata", JSONB, default=dict)

    # timestamps
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), onupdate=func.now())
    sent_at         = Column(DateTime(timezone=True))

    __table_args__ = (
        # idempotency — DB level safety net against duplicates
        UniqueConstraint("idempotency_key", name="uq_notifications_idempotency_key"),
        # index for worker query — fetch retrying notifications efficiently
        Index("ix_notifications_worker", "status", "priority", "next_retry_at"),
    )

    def __repr__(self):
        return (
            f"<Notification id={self.id} "
            f"channel={self.channel} "
            f"status={self.status} "
            f"priority={self.priority}>"
        )