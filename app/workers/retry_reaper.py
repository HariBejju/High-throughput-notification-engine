import asyncio
import logging
from datetime import datetime

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.notification import Notification, NotificationStatus
from app.services.queue_service import QueueService

logger = logging.getLogger(__name__)

REAPER_INTERVAL = 15  # seconds


class RetryReaper:
    """
    Background task that runs every 15 seconds.
    Finds RETRYING notifications whose next_retry_time has passed
    and re-enqueues them into the priority queue.

    This is what makes retry with exponential backoff work —
    workers never wait, reaper handles the scheduling.
    """

    def __init__(self, queue: QueueService):
        self.queue = queue
        self._running = False

    async def start(self):
        self._running = True
        asyncio.create_task(self._reap_loop())
        logger.info("RetryReaper started — checking every %ds", REAPER_INTERVAL)

    async def stop(self):
        self._running = False

    async def _reap_loop(self):
        while self._running:
            await asyncio.sleep(REAPER_INTERVAL)
            try:
                await self._requeue_due_retries()
            except Exception as e:
                logger.exception("RetryReaper error: %s", e)

    async def _requeue_due_retries(self):
        now = datetime.utcnow()

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Notification).where(
                    Notification.status == NotificationStatus.RETRYING,
                    Notification.next_retry_time <= now,
                )
            )
            due = result.scalars().all()

        if not due:
            return

        logger.info("RetryReaper found %d notifications due for retry", len(due))

        for notification in due:
            enqueued = await self.queue.enqueue(
                notification_id=notification.id,
                priority=notification.priority,
            )
            if enqueued:
                logger.info(
                    "Re-enqueued notification %s attempt %d",
                    notification.id, notification.retry_count
                )