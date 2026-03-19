from enum import Enum
from sqlalchemy import Column, BigInteger, Integer, String, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy import DateTime
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
    CRITICAL = 1
    HIGH     = 2
    MEDIUM   = 3
    LOW      = 4


class SourceService(int, Enum):
    ORDER    = 1
    PAYMENT  = 2
    SHIPPING = 3


class EventType(int, Enum):
    ORDER_CREATED           = 1
    ORDER_CANCELLED         = 2
    PAYMENT_CONFIRMED       = 3
    PAYMENT_FAILED          = 4
    PAYMENT_OTP_REQUESTED   = 5
    SHIPMENT_DISPATCHED     = 6
    SHIPMENT_DELIVERED      = 7
    SHIPMENT_DELAYED        = 8


class NotificationErrorCode(int, Enum):
    TIMEOUT           = 1   # retryable
    PROVIDER_DOWN     = 2   # retryable
    RATE_LIMITED      = 3   # retryable
    INVALID_RECIPIENT = 4   # not retryable
    INVALID_TOKEN     = 5   # not retryable
    UNKNOWN           = 6   # retryable


# retryable error codes — used by retry reaper
RETRYABLE_ERROR_CODES = {
    NotificationErrorCode.TIMEOUT,
    NotificationErrorCode.PROVIDER_DOWN,
    NotificationErrorCode.RATE_LIMITED,
    NotificationErrorCode.UNKNOWN,
}


class Notification(Base):
    __tablename__ = "notifications"

    id              = Column(BigInteger, primary_key=True, autoincrement=True)
    idempotency_key = Column(String(255), nullable=False)

    source_service  = Column(Integer, nullable=False)   # SourceService enum
    event_type      = Column(Integer, nullable=False)   # EventType enum
    channel         = Column(Integer, nullable=False)   # NotificationChannel enum
    recipient       = Column(String(255), nullable=False)

    priority        = Column(Integer, default=NotificationPriority.MEDIUM, nullable=False)
    status          = Column(Integer, default=NotificationStatus.PENDING, nullable=False)

    error_code      = Column(Integer, nullable=True)    # NotificationErrorCode enum
    retry_count     = Column(Integer, default=0)
    next_retry_time = Column(DateTime(timezone=True), nullable=True)
    external_id     = Column(String(255), nullable=True)

    # channel specific content — subject/body/title etc
    content         = Column(JSONB, nullable=False)

    ctime           = Column(DateTime(timezone=True), server_default=func.now())
    mtime           = Column(DateTime(timezone=True), onupdate=func.now())
    stime           = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_notifications_idempotency_key"),
        Index("ix_notifications_worker", "status", "priority", "next_retry_time"),
        Index("ix_notifications_channel", "channel"),
        Index("ix_notifications_event_type", "event_type"),
    )

    def __repr__(self):
        return (
            f"<Notification id={self.id} "
            f"channel={NotificationChannel(self.channel).name} "
            f"status={NotificationStatus(self.status).name} "
            f"priority={NotificationPriority(self.priority).name}>"
        )