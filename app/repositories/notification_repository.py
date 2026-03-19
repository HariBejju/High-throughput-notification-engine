import logging
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.notification import (
    Notification,
    NotificationStatus,
    NotificationChannel,
    SourceService,
    EventType,
)

logger = logging.getLogger(__name__)


class NotificationRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, notification: Notification) -> Notification:
        self.db.add(notification)
        await self.db.commit()
        await self.db.refresh(notification)
        return notification

    async def get_by_id(self, notification_id: int) -> Optional[Notification]:
        result = await self.db.execute(
            select(Notification).where(Notification.id == notification_id)
        )
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(self, key: str) -> Optional[Notification]:
        result = await self.db.execute(
            select(Notification).where(Notification.idempotency_key == key)
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        status: Optional[int] = None,
        channel: Optional[int] = None,
        source_service: Optional[int] = None,
        event_type: Optional[int] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Notification]:
        query = select(Notification)

        if status is not None:
            query = query.where(Notification.status == status)
        if channel is not None:
            query = query.where(Notification.channel == channel)
        if source_service is not None:
            query = query.where(Notification.source_service == source_service)
        if event_type is not None:
            query = query.where(Notification.event_type == event_type)

        query = query.order_by(Notification.ctime.desc()).limit(limit).offset(offset)
        result = await self.db.execute(query)
        return result.scalars().all()

    async def update_status(
        self,
        notification_id: int,
        status: NotificationStatus,
        **kwargs,
    ) -> Optional[Notification]:
        notification = await self.get_by_id(notification_id)
        if not notification:
            return None
        notification.status = status.value
        for key, value in kwargs.items():
            setattr(notification, key, value)
        await self.db.commit()
        await self.db.refresh(notification)
        return notification