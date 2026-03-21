import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Dict

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
# max_retries  ──► how many attempts before DLQ
# max_delay    ──► cap on delay in seconds
# use_jitter   ──► True for bulk events (thundering herd risk)
#                  False for single user events like OTP (fast retry needed)
RETRY_CONFIG = {
    EventType.PAYMENT_OTP_REQUESTED: {
        "max_retries": 3,
        "max_delay": 30,        # OTP expires in 5 min, keep retries fast
        "use_jitter": False,    # single user, no thundering herd risk
    },
    EventType.PAYMENT_FAILED: {
        "max_retries": 7,
        "max_delay": 3600,
        "use_jitter": True,     # bulk, thousands of users affected simultaneously
    },
    EventType.PAYMENT_CONFIRMED: {
        "max_retries": 7,
        "max_delay": 3600,
        "use_jitter": True,
    },
    EventType.ORDER_CREATED: {
        "max_retries": 10,
        "max_delay": 86400,
        "use_jitter": True,
    },
    EventType.ORDER_CANCELLED: {
        "max_retries": 10,
        "max_delay": 86400,
        "use_jitter": True,
    },
    EventType.SHIPMENT_DISPATCHED: {
        "max_retries": 10,
        "max_delay": 86400,
        "use_jitter": True,
    },
    EventType.SHIPMENT_DELIVERED: {
        "max_retries": 10,
        "max_delay": 86400,
        "use_jitter": True,
    },
    EventType.SHIPMENT_DELAYED: {
        "max_retries": 7,
        "max_delay": 3600,
        "use_jitter": True,
    },
}

DEFAULT_RETRY_CONFIG = {"max_retries": 5, "max_delay": 3600, "use_jitter": True}


def get_retry_delay(retry_count: int, max_delay: int, use_jitter: bool = True) -> int:
    """
    Exponential backoff with optional full jitter.

    use_jitter=True  ──► bulk notifications
                         random delay across full window
                         prevents thundering herd when provider recovers
                         1000 retries spread across window not all at once

    use_jitter=False ──► OTP and single user notifications
                         fixed predictable delay
                         fastest possible retry
                         no thundering herd risk for single user
    """
    base_delay = 30 * (2 ** (retry_count - 1))
    capped = min(base_delay, max_delay)

    if use_jitter:
        return random.randint(1, capped)
    else:
        return capped


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
            notification_id,
            NotificationStatus.QUEUED,
        )

        healthy = await provider.health_check()
        if not healthy:
            logger.warning(
                "Provider %s is down — scheduling retry for %s",
                channel.name, notification_id
            )
            await self._schedule_retry(notification, NotificationErrorCode.PROVIDER_DOWN)
            return

        result = await provider.send(notification.recipient, notification.content)

        if result.success:
            await self._mark_sent(notification, result.external_id)
        else:
            error_code = NotificationErrorCode(result.error_code) if result.error_code else NotificationErrorCode.UNKNOWN

            if error_code not in RETRYABLE_ERROR_CODES:
                logger.warning(
                    "Non retryable error for %s error=%s",
                    notification_id, error_code.name
                )
                await self._mark_failed(notification, error_code)
            else:
                await self._schedule_retry(notification, error_code)

    async def _mark_sent(self, notification: Notification, external_id: str):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        await self.repository.update_status(
            notification.id,
            NotificationStatus.SENT,
            external_id=external_id,
            stime=now,
        )
        logger.info(
            "Notification %s SENT channel=%s",
            notification.id,
            NotificationChannel(notification.channel).name
        )

    async def _mark_failed(self, notification: Notification, error_code: NotificationErrorCode):
        await self.repository.update_status(
            notification.id,
            NotificationStatus.FAILED,
            error_code=error_code.value,
        )
        logger.error(
            "Notification %s FAILED permanently channel=%s error=%s retries=%d",
            notification.id,
            NotificationChannel(notification.channel).name,
            error_code.name,
            notification.retry_count,
        )

    async def _schedule_retry(
        self,
        notification: Notification,
        error_code: NotificationErrorCode = NotificationErrorCode.PROVIDER_DOWN,
    ):
        event_type = EventType(notification.event_type)
        config = RETRY_CONFIG.get(event_type, DEFAULT_RETRY_CONFIG)
        max_retries = config["max_retries"]
        max_delay   = config["max_delay"]
        use_jitter  = config["use_jitter"]

        new_retry_count = notification.retry_count + 1

        if new_retry_count > max_retries:
            logger.error(
                "Notification %s exhausted %d retries — sending to DLQ",
                notification.id, max_retries
            )
            await self._mark_failed(notification, error_code)
            await self._send_to_dlq(notification, error_code)
            return

        delay = get_retry_delay(new_retry_count, max_delay, use_jitter)
        next_retry_time = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=delay)

        await self.repository.update_status(
            notification.id,
            NotificationStatus.RETRYING,
            retry_count=new_retry_count,
            error_code=error_code.value,
            next_retry_time=next_retry_time,
        )

        logger.info(
            "Notification %s RETRYING attempt %d/%d delay=%ds jitter=%s error=%s",
            notification.id, new_retry_count, max_retries,
            delay, use_jitter, error_code.name
        )

    async def _send_to_dlq(self, notification: Notification, error_code: NotificationErrorCode):
        try:
            import aio_pika
            import json

            connection = await aio_pika.connect_robust(settings.rabbitmq_url)
            async with connection:
                channel = await connection.channel()

                dlq_exchange = await channel.declare_exchange(
                    "notification.dlq.exchange",
                    aio_pika.ExchangeType.FANOUT,
                    durable=True,
                )

                dlq_queue = await channel.declare_queue(
                    "notification.dlq",
                    durable=True,
                )
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