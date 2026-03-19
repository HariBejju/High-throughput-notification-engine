import uuid
import logging

import redis.asyncio as aioredis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.notification import Notification, NotificationStatus
from app.repositories.notification_repository import NotificationRepository
from app.schemas.notification_request import NotificationCreate

logger = logging.getLogger(__name__)

IDEMPOTENCY_EXPIRY = 86400  # 24 hours

redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)


class NotificationManager:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = NotificationRepository(db)

    async def create_notification(self, payload: NotificationCreate) -> tuple[Notification | None, bool]:
        """
        Returns (notification, is_duplicate)
        is_duplicate = True means same idempotency key already processed
        """
        # Step 1 — fast idempotency check via Redis
        redis_key = f"idem:{payload.idempotency_key}"
        is_new = await redis_client.setnx(redis_key, "1")

        if not is_new:
            logger.info("Duplicate blocked by Redis: %s", payload.idempotency_key)
            return None, True

        # set expiry after successful setnx
        await redis_client.expire(redis_key, IDEMPOTENCY_EXPIRY)

        # Step 2 — build notification object
        notification = Notification(
            id=uuid.uuid4(),
            idempotency_key=payload.idempotency_key,
            source_service=payload.source_service_as_int(),
            event_type=payload.event_type,
            channel=payload.channel_as_int(),
            recipient=payload.recipient,
            subject=payload.subject,
            body=payload.body,
            priority=payload.priority,
            status=NotificationStatus.PENDING,
            metadata_=payload.metadata,
        )

        # Step 3 — persist to DB
        try:
            saved = await self.repository.create(notification)
            logger.info("Notification created: %s", saved.id)
            return saved, False

        except IntegrityError:
            # PostgreSQL unique constraint caught duplicate Redis missed
            await self.db.rollback()
            await redis_client.delete(redis_key)
            logger.warning("Duplicate caught by DB: %s", payload.idempotency_key)
            return None, True

    async def get_notification(self, notification_id: uuid.UUID):
        return await self.repository.get_by_id(notification_id)

    async def list_notifications(
        self,
        status=None,
        channel=None,
        source_service=None,
        limit=20,
        offset=0,
    ):
        return await self.repository.list(
            status=status,
            channel=channel,
            source_service=source_service,
            limit=limit,
            offset=offset,
        )