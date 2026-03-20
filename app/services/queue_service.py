import logging
import time
from typing import Optional

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

QUEUE_KEY = "notification:queue"


class QueueService:
    """
    Priority queue using Redis Sorted Set.

    Score = priority * 10^12 + timestamp
    This ensures:
      1. Lower priority number = higher priority (OTP first)
      2. Within same priority — older notifications processed first (FIFO)

    Redis commands used:
      ZADD  ──► add notification to queue with score
      BZPOPMIN ──► blocking pop of lowest score (highest priority)
      ZCARD ──► queue depth
    """

    def __init__(self):
        self.redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    async def enqueue(self, notification_id: int, priority: int) -> bool:
        """
        Add notification to priority queue.
        Score = priority * 10^12 + current timestamp in ms
        Ensures priority ordering with FIFO within same priority.
        """
        try:
            timestamp_ms = int(time.time() * 1000)
            score = priority * (10 ** 12) + timestamp_ms

            await self.redis.zadd(
                QUEUE_KEY,
                {str(notification_id): score},
                nx=True,  # only add if not already in queue
            )
            logger.debug("Enqueued notification %s with score %s", notification_id, score)
            return True

        except Exception as e:
            logger.error("Failed to enqueue notification %s: %s", notification_id, e)
            return False

    async def dequeue(self) -> Optional[int]:
        """
        Pop highest priority notification from queue.
        Returns notification_id or None if queue is empty.
        Uses BZPOPMIN with 1 second timeout so workers don't spin.
        """
        try:
            result = await self.redis.bzpopmin(QUEUE_KEY, timeout=1)
            if result:
                # result = (queue_key, member, score)
                _, notification_id, _ = result
                return int(notification_id)
            return None

        except Exception as e:
            logger.error("Failed to dequeue: %s", e)
            return None

    async def depth(self) -> int:
        """Return current queue depth"""
        try:
            return await self.redis.zcard(QUEUE_KEY)
        except Exception:
            return 0

    async def remove(self, notification_id: int):
        """Remove a specific notification from queue"""
        try:
            await self.redis.zrem(QUEUE_KEY, str(notification_id))
        except Exception as e:
            logger.error("Failed to remove %s from queue: %s", notification_id, e)