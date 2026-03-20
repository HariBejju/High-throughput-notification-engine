import asyncio
import json
import logging

import aio_pika
from aio_pika.abc import AbstractIncomingMessage

from app.config import settings
from app.database import AsyncSessionLocal
from app.managers.notification_manager import NotificationManager
from app.schemas.notification_request import NotificationCreate, RecipientInfo

logger = logging.getLogger(__name__)

EXCHANGE_NAME = "notification.exchange"
QUEUE_NAME    = "notification.queue"
ROUTING_KEYS  = ["order.*", "payment.*", "shipping.*"]


class RabbitMQHandler:

    def __init__(self):
        self._connection = None
        self._channel    = None
        self._running    = False

    async def start(self):
        try:
            self._connection = await aio_pika.connect_robust(settings.rabbitmq_url)
            self._channel    = await self._connection.channel()
            await self._channel.set_qos(prefetch_count=10)

            exchange = await self._channel.declare_exchange(
                EXCHANGE_NAME,
                aio_pika.ExchangeType.TOPIC,
                durable=True,
            )

            queue = await self._channel.declare_queue(
                QUEUE_NAME,
                durable=True,
            )

            for routing_key in ROUTING_KEYS:
                await queue.bind(exchange, routing_key=routing_key)

            await queue.consume(self._on_message)
            self._running = True
            logger.info("RabbitMQ consumer started — listening on %s", QUEUE_NAME)

        except Exception as e:
            logger.error("Failed to connect to RabbitMQ: %s", e)

    async def stop(self):
        self._running = False
        if self._connection:
            await self._connection.close()

    async def _on_message(self, message: AbstractIncomingMessage):
        """Process incoming RabbitMQ message"""
        logger.info(
            "Message received routing_key=%s body=%s",
            message.routing_key,
            message.body.decode()[:200]
        )

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
                logger.info(
                    "Created %d notifications for %s",
                    len(notifications), body["idempotency_key"]
                )

            await message.ack()

        except json.JSONDecodeError as e:
            logger.error("Invalid JSON: %s", e)
            await message.nack(requeue=False)

        except KeyError as e:
            logger.error("Missing field in event: %s", e)
            await message.nack(requeue=False)

        except Exception as e:
            logger.exception("Error processing message: %s", e)
            await message.nack(requeue=True)