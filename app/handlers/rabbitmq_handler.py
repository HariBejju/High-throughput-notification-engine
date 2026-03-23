import asyncio
import json
import logging

import aio_pika
from aio_pika.abc import AbstractIncomingMessage

from app.config import settings
from app.database import AsyncSessionLocal
from app.managers.notification_manager import NotificationManager
from app.schemas.notification_request import NotificationCreate, RecipientInfo
from app.services.queue_service import QueueService
from app.repositories.notification_repository import NotificationRepository

logger = logging.getLogger(__name__)

EXCHANGE_NAME = "notification.exchange"
QUEUE_NAME    = "notification.queue"
RETRY_QUEUE   = "notification.retry"
ROUTING_KEYS  = ["order.*", "payment.*", "shipping.*", "order.retry"]


class RabbitMQHandler:
    """
    Two responsibilities:
    1. Consume new events from notification.queue
    2. Consume retried notifications from notification.retry queue
       (messages arrive here after TTL expires — no polling needed)
    """

    def __init__(self, queue_service: QueueService):
        self._connection  = None
        self._channel     = None
        self._running     = False
        self.queue_service = queue_service

    async def start(self):
        try:
            self._connection = await aio_pika.connect_robust(settings.rabbitmq_url)
            self._channel    = await self._connection.channel()
            await self._channel.set_qos(prefetch_count=100)

            # main exchange
            exchange = await self._channel.declare_exchange(
                EXCHANGE_NAME,
                aio_pika.ExchangeType.TOPIC,
                durable=True,
            )

            # main queue for new events
            queue = await self._channel.declare_queue(QUEUE_NAME, durable=True)
            for routing_key in ROUTING_KEYS:
                await queue.bind(exchange, routing_key=routing_key)

            # retry queue — messages arrive here after TTL expires
            # x-dead-letter-exchange routes expired messages back to main exchange
            retry_queue = await self._channel.declare_queue(
                RETRY_QUEUE,
                durable=True,
                arguments={
                    "x-dead-letter-exchange": EXCHANGE_NAME,
                    "x-dead-letter-routing-key": "order.retry",
                }
            )

            await queue.consume(self._on_new_event)
            await retry_queue.consume(self._on_retry_event)

            self._running = True
            logger.info("RabbitMQ consumer started — listening on %s and %s", QUEUE_NAME, RETRY_QUEUE)

        except Exception as e:
            logger.error("Failed to connect to RabbitMQ: %s", e)
            logger.info("Service will continue without RabbitMQ — use REST API")

    async def stop(self):
        self._running = False
        if self._connection:
            await self._connection.close()

    async def _on_new_event(self, message: AbstractIncomingMessage):
        """Handles new events from microservices"""
        logger.info("New event received routing_key=%s", message.routing_key)
        try:
            body = json.loads(message.body.decode())

            payload = NotificationCreate(
                idempotency_key=body["idempotency_key"],
                source_service=body["source_service"],
                event_type=body["event_type"],
                priority=body.get("priority", "medium"),
                recipient=RecipientInfo(**body["recipient"]),
                content=body["content"],
            )

            async with AsyncSessionLocal() as db:
                manager = NotificationManager(db)
                notifications, is_duplicate = await manager.create_notification(payload)

            if is_duplicate:
                logger.info("Duplicate skipped: %s", body["idempotency_key"])
            else:
                logger.info("Created %d notifications for %s", len(notifications), body["idempotency_key"])

            await message.ack()

        except json.JSONDecodeError as e:
            logger.error("Invalid JSON: %s", e)
            await message.nack(requeue=False)
        except KeyError as e:
            logger.error("Missing field: %s", e)
            await message.nack(requeue=False)
        except Exception as e:
            logger.exception("Error processing new event: %s", e)
            await message.nack(requeue=True)

    async def _on_retry_event(self, message: AbstractIncomingMessage):
        """
        Handles retried notifications.
        Message body is just the notification_id.
        TTL expired in retry queue — time to try again.
        No polling — RabbitMQ fired this exactly when delay expired.
        """
        try:
            notification_id = int(message.body.decode())
            logger.info("Retry event received for notification %s", notification_id)

            async with AsyncSessionLocal() as db:
                repo = NotificationRepository(db)
                notification = await repo.get_by_id(notification_id)

            if notification:
                await self.queue_service.enqueue(
                    notification_id=notification.id,
                    priority=notification.priority,
                )
                logger.info("Re-enqueued notification %s for retry", notification_id)
            else:
                logger.warning("Notification %s not found for retry", notification_id)

            await message.ack()

        except Exception as e:
            logger.exception("Error processing retry event: %s", e)
            await message.nack(requeue=False)