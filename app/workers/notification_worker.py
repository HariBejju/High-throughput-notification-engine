import asyncio
import logging
from typing import Dict

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.notification import NotificationChannel
from app.providers.base import BaseProvider
from app.services.dispatch_service import DispatchService
from app.services.queue_service import QueueService

logger = logging.getLogger(__name__)


class NotificationWorker:
    """
    Worker pool — N async coroutines continuously pulling
    from the priority queue and dispatching notifications.

    At 50,000/min = 834/sec with 100ms avg latency:
    Workers needed = 834 × 0.1 = ~84, we run 100 for headroom.

    Each worker is a lightweight async coroutine — not an OS thread.
    All 100 workers share one event loop.
    """

    def __init__(
        self,
        queue: QueueService,
        providers: Dict[NotificationChannel, BaseProvider],
        concurrency: int = None,
    ):
        self.queue = queue
        self.providers = providers
        self.concurrency = concurrency or settings.worker_count
        self._running = False
        self._tasks = []

    async def start(self):
        self._running = True
        logger.info("Starting %d notification workers", self.concurrency)
        self._tasks = [
            asyncio.create_task(self._worker_loop(worker_id=i))
            for i in range(self.concurrency)
        ]

    async def stop(self):
        self._running = False
        await asyncio.gather(*self._tasks, return_exceptions=True)
        logger.info("All workers stopped")

    async def _worker_loop(self, worker_id: int):
        logger.debug("Worker %d started", worker_id)
        while self._running:
            try:
                notification_id = await self.queue.dequeue()

                if notification_id is None:
                    # queue empty — loop back and wait
                    continue

                # each notification gets its own DB session
                async with AsyncSessionLocal() as db:
                    dispatch_service = DispatchService(
                        db=db,
                        providers=self.providers,
                        queue=self.queue,
                    )
                    await dispatch_service.dispatch(notification_id)

            except Exception as e:
                logger.exception("Worker %d error: %s", worker_id, e)