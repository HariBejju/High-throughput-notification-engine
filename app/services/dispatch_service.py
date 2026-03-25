import logging
import random
from datetime import datetime, timezone
from typing import Dict

import aio_pika
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.notification import (
    Notification,
    NotificationStatus,
    NotificationChannel,
    NotificationErrorCode,
    EventType,
    RETRYABLE_ERROR_CODES,
)
from app.providers.base import BaseProvider
from app.repositories.notification_repository import NotificationRepository
from app.services.queue_service import QueueService

logger = logging.getLogger(__name__)

# per event type retry config
RETRY_CONFIG = {
    EventType.PAYMENT_OTP_REQUESTED: {
        "max_retries": 3,
        "base_delay":  5,      # OTP — 5s base, matches critical check interval
        "max_delay":   30,
        "use_jitter":  False,  # single user, no thundering herd
    },
    EventType.PAYMENT_FAILED: {
        "max_retries": 3,
        "base_delay":  15,
        "max_delay":   3600,
        "use_jitter":  True,
    },
    EventType.PAYMENT_CONFIRMED: {
        "max_retries": 3,
        "base_delay":  15,
        "max_delay":   3600,
        "use_jitter":  True,
    },
    EventType.ORDER_CREATED: {
        "max_retries": 3,
        "base_delay":  15,
        "max_delay":   3600,
        "use_jitter":  True,
    },
    EventType.ORDER_CANCELLED: {
        "max_retries": 3,
        "base_delay":  15,
        "max_delay":   3600,
        "use_jitter":  True,
    },
    EventType.SHIPMENT_DISPATCHED: {
        "max_retries": 3,
        "base_delay":  15,
        "max_delay":   3600,
        "use_jitter":  True,
    },
    EventType.SHIPMENT_DELIVERED: {
        "max_retries": 3,
        "base_delay":  15,
        "max_delay":   3600,
        "use_jitter":  True,
    },
    EventType.SHIPMENT_DELAYED: {
        "max_retries": 3,
        "base_delay":  15,
        "max_delay":   3600,
        "use_jitter":  True,
    },
}

DEFAULT_RETRY_CONFIG = {
    "max_retries": 3,
    "base_delay":  15,
    "max_delay":   3600,
    "use_jitter":  True,
}


def get_retry_delay(retry_count: int, base_delay: int, max_delay: int, use_jitter: bool) -> int:
    """
    Exponential backoff with proper window jitter.

    Each retry level has its own distinct window — no overlap between levels:

    bulk (base=15):
        retry 1 ──► random(15, 30)
        retry 2 ──► random(30, 60)
        retry 3 ──► random(60, 120)  capped at max_delay

    OTP (base=5, no jitter):
        retry 1 ──► 5s  (fixed)
        retry 2 ──► 10s (fixed)
        retry 3 ──► 20s (fixed)

    use_jitter=True  ──► random within window, prevents thundering herd
    use_jitter=False ──► always returns low end of window (fastest retry for OTP)
    """
    low  = base_delay * (2 ** (retry_count - 1))
    high = base_delay * (2 ** retry_count)

    low  = min(low, max_delay)
    high = min(high, max_delay)

    if use_jitter:
        return random.randint(low, high)
    return low


class DispatchService:

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
        notification = await self.repository.get_by_id(notification_id)
        if not notification:
            logger.error("Notification %s not found", notification_id)
            return

        channel = NotificationChannel(notification.channel)
        provider = self.providers.get(channel)

        if not provider:
            logger.error("No provider for channel %s", channel)
            await self._mark_failed(notification, NotificationErrorCode.UNKNOWN)
            return

        await self.repository.update_status(
            notification_id, NotificationStatus.QUEUED
        )

        healthy = await provider.health_check()
        if not healthy:
            logger.warning("Provider %s down — scheduling retry for %s", channel.name, notification_id)
            await self._schedule_retry(notification, NotificationErrorCode.PROVIDER_DOWN)
            return

        result = await provider.send(notification.recipient, notification.content)

        if result.success:
            await self._mark_sent(notification, result.external_id)
        else:
            error_code = NotificationErrorCode(result.error_code) if result.error_code else NotificationErrorCode.UNKNOWN
            if error_code not in RETRYABLE_ERROR_CODES:
                logger.warning("Non retryable error for %s error=%s", notification_id, error_code.name)
                await self._mark_failed(notification, error_code)
            else:
                await self._schedule_retry(notification, error_code)

    async def _mark_sent(self, notification: Notification, external_id: str):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        await self.repository.update_status(
            notification.id, NotificationStatus.SENT,
            external_id=external_id, stime=now,
        )
        logger.info("Notification %s SENT channel=%s", notification.id, NotificationChannel(notification.channel).name)

    async def _mark_failed(self, notification: Notification, error_code: NotificationErrorCode):
        await self.repository.update_status(
            notification.id, NotificationStatus.FAILED,
            error_code=error_code.value,
        )
        logger.error(
            "Notification %s FAILED permanently channel=%s error=%s retries=%d",
            notification.id, NotificationChannel(notification.channel).name,
            error_code.name, notification.retry_count,
        )

    async def _schedule_retry(
        self,
        notification: Notification,
        error_code: NotificationErrorCode = NotificationErrorCode.PROVIDER_DOWN,
    ):
        event_type = EventType(notification.event_type)
        config = RETRY_CONFIG.get(event_type, DEFAULT_RETRY_CONFIG)
        max_retries = config["max_retries"]
        base_delay  = config["base_delay"]
        max_delay   = config["max_delay"]
        use_jitter  = config["use_jitter"]

        new_retry_count = notification.retry_count + 1

        if new_retry_count > max_retries:
            logger.error("❌ Notification %s exhausted %d retries — sending to DLQ", notification.id, max_retries)
            await self._mark_failed(notification, error_code)
            await self._send_to_dlq(notification, error_code)
            return

        delay = get_retry_delay(new_retry_count, base_delay, max_delay, use_jitter)

        # update DB status
        await self.repository.update_status(
            notification.id, NotificationStatus.RETRYING,
            retry_count=new_retry_count,
            error_code=error_code.value,
        )

        # publish to RabbitMQ retry queue with TTL
        # when TTL expires RabbitMQ routes back to main queue automatically
        # zero polling, zero wasted resources during quiet periods
        success = await self.queue.publish_retry(notification.id, delay)
        if not success:
            logger.error(
                "❌ CRITICAL: Failed to publish retry — notification %s stuck in RETRYING state",
                notification.id
            )
            return

        logger.info(
            "⏰ Notification %s RETRYING attempt %d/%d | delay=%ds | jitter=%s | error=%s | Will auto-retry after TTL",
            notification.id, new_retry_count, max_retries, delay, use_jitter, error_code.name
        )

    async def _send_to_dlq(self, notification: Notification, error_code: NotificationErrorCode):
        try:
            import json
            connection = await aio_pika.connect_robust(settings.rabbitmq_url)
            async with connection:
                channel = await connection.channel()

                dlq_exchange = await channel.declare_exchange(
                    "notification.dlq.exchange",
                    aio_pika.ExchangeType.FANOUT,
                    durable=True,
                )
                dlq_queue = await channel.declare_queue("notification.dlq", durable=True)
                await dlq_queue.bind(dlq_exchange)

                payload = {
                    "notification_id": notification.id,
                    "idempotency_key": notification.idempotency_key,
                    "event_type": EventType(notification.event_type).name.lower(),
                    "channel": NotificationChannel(notification.channel).name.lower(),
                    "recipient": notification.recipient,
                    "error_code": error_code.name.lower(),
                    "retry_count": notification.retry_count,
                    "failure_reason": f"Exhausted all retries. Last error: {error_code.name}",
                    "failed_at": datetime.now(timezone.utc).isoformat(),
                }

                await dlq_exchange.publish(
                    aio_pika.Message(
                        body=json.dumps(payload).encode(),
                        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                        content_type="application/json",
                    ),
                    routing_key="",
                )
                logger.info("Notification %s published to DLQ", notification.id)

        except Exception as e:
            logger.error("Failed to publish to DLQ: %s", e)