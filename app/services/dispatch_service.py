import logging
from datetime import datetime, timedelta
from typing import Dict

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.notification import (
    Notification,
    NotificationStatus,
    NotificationChannel,
    NotificationErrorCode,
    RETRYABLE_ERROR_CODES,
)
from app.providers.base import BaseProvider
from app.repositories.notification_repository import NotificationRepository
from app.services.queue_service import QueueService

logger = logging.getLogger(__name__)

# exponential backoff delays per retry attempt
RETRY_DELAYS = [30, 120, 600]   # 30s → 2min → 10min


class DispatchService:
    """
    Orchestrates the full send pipeline:
    1. Get notification from DB
    2. Check provider health (circuit breaker)
    3. Send via correct provider
    4. Update status based on result
    5. Schedule retry if failed
    """

    def __init__(
        self,
        db: AsyncSession,
        providers: Dict[NotificationChannel, BaseProvider],
        queue: QueueService,
    ):
        self.db = db
        self.providers = providers
        self.queue = queue
        self.repository = NotificationRepository(db)

    async def dispatch(self, notification_id: int):
        """Main dispatch method called by worker"""

        notification = await self.repository.get_by_id(notification_id)
        if not notification:
            logger.error("Notification %s not found", notification_id)
            return

        # get correct provider for this channel
        channel = NotificationChannel(notification.channel)
        provider = self.providers.get(channel)

        if not provider:
            logger.error("No provider for channel %s", channel)
            await self._mark_failed(notification, NotificationErrorCode.UNKNOWN)
            return

        # update status to QUEUED
        await self.repository.update_status(
            notification_id,
            NotificationStatus.QUEUED,
        )

        # check provider health — circuit breaker
        healthy = await provider.health_check()
        if not healthy:
            logger.warning("Provider %s is down — scheduling retry", channel.name)
            await self._schedule_retry(notification)
            return

        # send notification
        result = await provider.send(notification.recipient, notification.content)

        if result.success:
            await self._mark_sent(notification, result.external_id)
        else:
            # check if retryable
            error_code = NotificationErrorCode(result.error_code) if result.error_code else NotificationErrorCode.UNKNOWN

            if error_code not in RETRYABLE_ERROR_CODES:
                logger.warning(
                    "Non retryable error for %s: %s",
                    notification_id, result.error_message
                )
                await self._mark_failed(notification, error_code)
            else:
                await self._schedule_retry(notification, error_code)

    async def _mark_sent(self, notification: Notification, external_id: str):
        now = datetime.utcnow()
        await self.repository.update_status(
            notification.id,
            NotificationStatus.SENT,
            external_id=external_id,
            stime=now,
        )
        logger.info("Notification %s SENT", notification.id)

    async def _mark_failed(self, notification: Notification, error_code: NotificationErrorCode):
        await self.repository.update_status(
            notification.id,
            NotificationStatus.FAILED,
            error_code=error_code.value,
        )
        logger.error("Notification %s FAILED error_code=%s", notification.id, error_code.name)

    async def _schedule_retry(
        self,
        notification: Notification,
        error_code: NotificationErrorCode = NotificationErrorCode.PROVIDER_DOWN,
    ):
        new_retry_count = notification.retry_count + 1

        if new_retry_count > settings.max_retries:
            logger.error(
                "Notification %s exhausted retries — marking FAILED",
                notification.id
            )
            await self._mark_failed(notification, error_code)
            return

        delay = RETRY_DELAYS[min(new_retry_count - 1, len(RETRY_DELAYS) - 1)]
        next_retry_time = datetime.utcnow() + timedelta(seconds=delay)

        await self.repository.update_status(
            notification.id,
            NotificationStatus.RETRYING,
            retry_count=new_retry_count,
            error_code=error_code.value,
            next_retry_time=next_retry_time,
        )

        logger.info(
            "Notification %s RETRYING attempt %d/%d at %s",
            notification.id, new_retry_count, settings.max_retries, next_retry_time
        )