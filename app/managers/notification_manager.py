import logging
from typing import Optional, List, Tuple

import redis.asyncio as aioredis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.event_channel_map import EVENT_CHANNEL_MAP, CHANNEL_RECIPIENT_FIELD
from app.models.notification import (
    Notification,
    NotificationStatus,
    NotificationChannel,
    SourceService,
    EventType,
)
from app.repositories.notification_repository import NotificationRepository
from app.schemas.notification_request import NotificationCreate
from app.services.queue_service import QueueService

logger = logging.getLogger(__name__)

# per event type idempotency key TTL
# OTP expires in 5 minutes — no point holding key longer
# bulk events held for 24 hours to cover producer retry windows
IDEMPOTENCY_TTL = {
    "payment_otp_requested": 300,    # 5 minutes
    "payment_failed":        86400,  # 24 hours
    "payment_confirmed":     86400,
    "order_created":         86400,
    "order_cancelled":       86400,
    "shipment_dispatched":   86400,
    "shipment_delivered":    86400,
    "shipment_delayed":      86400,
}
DEFAULT_IDEMPOTENCY_TTL = 86400  # 24 hours fallback

redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
queue_service = QueueService()


class NotificationManager:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = NotificationRepository(db)

    async def create_notification(
        self, payload: NotificationCreate
    ) -> Tuple[List[Notification], bool]:
        """
        Creates one notification per channel based on EVENT_CHANNEL_MAP.
        Returns (notifications, is_duplicate)

        Idempotency is two layer:
        Layer 1 — Redis SETNX (0.1ms, blocks before DB)
        Layer 2 — PostgreSQL UNIQUE constraint (safety net)

        Edge case handled — if SETNX succeeds but DB write fails
        (e.g. network blip), next retry finds Redis key set but no DB row.
        We detect this and reprocess instead of silently dropping.
        """
        redis_key = f"idem:{payload.idempotency_key}"
        ttl = IDEMPOTENCY_TTL.get(payload.event_type.lower(), DEFAULT_IDEMPOTENCY_TTL)

        is_new = await redis_client.setnx(redis_key, "1")

        if not is_new:
            # Redis key exists — but did DB write actually succeed?
            # If previous attempt failed after SETNX but before DB write
            # the notification was never created — we must not silently drop
            existing = await self.repository.get_by_idempotency_key(
                payload.idempotency_key
            )
            if existing:
                # DB row exists — genuine duplicate, drop it
                logger.info("Duplicate blocked by Redis: %s", payload.idempotency_key)
                return [], True
            else:
                # DB row missing — previous attempt failed mid-way
                # delete Redis key and reprocess so notification is not lost
                await redis_client.delete(redis_key)
                await redis_client.setnx(redis_key, "1")
                logger.warning(
                    "Partial failure detected for %s — Redis key existed but no DB row. Reprocessing.",
                    payload.idempotency_key
                )

        await redis_client.expire(redis_key, ttl)

        # get channels for this event type
        event = EventType[payload.event_type.upper()]
        channels = EVENT_CHANNEL_MAP.get(event, [])

        created = []

        for channel in channels:
            # generate per channel idempotency key
            channel_idem_key = f"{payload.idempotency_key}-{channel.name.lower()}"

            # get correct recipient for this channel
            recipient_field = CHANNEL_RECIPIENT_FIELD[channel]
            recipient = getattr(payload.recipient, recipient_field)

            # get content for this channel
            channel_content = payload.content.get(channel.name.lower(), {})

            notification = Notification(
                idempotency_key=channel_idem_key,
                source_service=payload.source_service_as_int(),
                event_type=payload.event_type_as_int(),
                channel=channel.value,
                recipient=recipient,
                priority=payload.priority_as_int(),
                status=NotificationStatus.PENDING,
                content=channel_content,
            )

            try:
                saved = await self.repository.create(notification)
                await queue_service.enqueue(
                    notification_id=saved.id,
                    priority=saved.priority,
                )
                created.append(saved)
                logger.info(
                    "Notification created id=%s channel=%s",
                    saved.id, channel.name
                )

            except IntegrityError:
                await self.db.rollback()
                logger.warning(
                    "Duplicate channel notification: %s", channel_idem_key
                )

        return created, False

    async def get_notification(self, notification_id: int) -> Optional[Notification]:
        return await self.repository.get_by_id(notification_id)

    async def list_notifications(
        self,
        status: Optional[str] = None,
        channel: Optional[str] = None,
        source_service: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Notification]:
        status_int = NotificationStatus[status.upper()].value if status else None
        channel_int = NotificationChannel[channel.upper()].value if channel else None
        source_int = SourceService[source_service.upper()].value if source_service else None
        event_int = EventType[event_type.upper()].value if event_type else None

        return await self.repository.list(
            status=status_int,
            channel=channel_int,
            source_service=source_int,
            event_type=event_int,
            limit=limit,
            offset=offset,
        )

    async def retry_notification(
        self, notification_id: int
    ) -> Tuple[Optional[Notification], str]:
        notification = await self.repository.get_by_id(notification_id)

        if not notification:
            return None, "Notification not found"

        if notification.status == NotificationStatus.SENT:
            return None, "Cannot retry a notification with status sent"

        if notification.status == NotificationStatus.QUEUED:
            return None, "Notification is already queued"

        updated = await self.repository.update_status(
            notification_id,
            NotificationStatus.PENDING,
            retry_count=notification.retry_count + 1,
            error_code=None,
            next_retry_time=None,
        )

        await queue_service.enqueue(
            notification_id=notification_id,
            priority=notification.priority,
        )

        return updated, ""