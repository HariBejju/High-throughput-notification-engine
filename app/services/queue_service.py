import logging
import time
from typing import Optional

import aio_pika
import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

QUEUE_KEY = "notification:queue"

# RabbitMQ retry constants
RETRY_QUEUE    = "notification.retry"
RETRY_EXCHANGE = "notification.retry.exchange"
MAIN_QUEUE     = "notification.queue"


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
        self._rmq_connection = None
        self._rmq_channel = None

    async def get_rabbitmq_channel(self):
        """
        Get or create persistent RabbitMQ connection and channel.
        Reuses connections instead of creating new ones per message.
        """
        try:
            if self._rmq_connection is None or self._rmq_connection.is_closed():
                self._rmq_connection = await aio_pika.connect_robust(settings.rabbitmq_url)
                self._rmq_channel = await self._rmq_connection.channel()
                logger.info("RabbitMQ connection established for retry queue")
            elif self._rmq_channel is None or self._rmq_channel.is_closed():
                self._rmq_channel = await self._rmq_connection.channel()
                
            return self._rmq_channel
        except Exception as e:
            logger.error("Failed to get RabbitMQ channel: %s", e)
            self._rmq_connection = None
            self._rmq_channel = None
            raise

    async def publish_retry(self, notification_id: int, delay_seconds: int) -> bool:
        """
        Publish notification to retry queue with TTL.
        Message will expire after delay_seconds and be routed to retry result queue
        via dead-letter exchange where it's re-enqueued to Redis.
        
        Returns True if successful, False otherwise.
        """
        try:
            channel = await self.get_rabbitmq_channel()
            
            logger.info(
                "🚀 Publishing notification %s to retry queue with TTL=%ds (will retry after expiration)",
                notification_id, delay_seconds
            )
            
            # Declare retry queue with dead-letter exchange
            retry_queue = await channel.declare_queue(
                RETRY_QUEUE,
                durable=True,
                arguments={
                    "x-dead-letter-exchange": RETRY_EXCHANGE,
                }
            )
            
            # Publish message with TTL expiration
            message = aio_pika.Message(
                body=str(notification_id).encode(),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                expiration=(int(delay_seconds)),  # TTL in milliseconds - ensure integer
            )
            
            await channel.default_exchange.publish(
                message,
                routing_key=RETRY_QUEUE,
            )
            
            logger.info(
                "✅ Notification %s published to retry queue | TTL expires in %ds | Will route via %s exchange",
                notification_id, delay_seconds, RETRY_EXCHANGE
            )
            return True
            
        except Exception as e:
            logger.error(
                "❌ CRITICAL: Failed to publish retry for notification %s: %s | Notification is STUCK in RETRYING state",
                notification_id, e
            )
            return False

    async def close_rabbitmq(self):
        """Close RabbitMQ connection"""
        try:
            if self._rmq_connection and not self._rmq_connection.is_closed():
                await self._rmq_connection.close()
                self._rmq_connection = None
                self._rmq_channel = None
                logger.info("RabbitMQ connection closed")
        except Exception as e:
            logger.error("Error closing RabbitMQ connection: %s", e)


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