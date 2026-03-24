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

IDEMPOTENCY_EXPIRY = 86400  # 24 hours

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
        """
        # check base idempotency key in Redis
        redis_key = f"idem:{payload.idempotency_key}"
        is_new = await redis_client.setnx(redis_key, "1")

        if not is_new:
            logger.info("Duplicate blocked by Redis: %s", payload.idempotency_key)
            return [], True

        await redis_client.expire(redis_key, IDEMPOTENCY_EXPIRY)

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