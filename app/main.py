import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import engine, Base
from app.controllers.notification_controller import router as notification_router
from app.handlers.exception_handler import register_exception_handlers
from app.handlers.rabbitmq_handler import RabbitMQHandler
from app.providers.email_provider import MockEmailProvider
from app.providers.sms_provider import MockSMSProvider
from app.providers.push_provider import MockPushProvider
from app.models.notification import NotificationChannel
from app.services.queue_service import QueueService
from app.workers.notification_worker import NotificationWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

# providers
providers = {
    NotificationChannel.EMAIL: MockEmailProvider(failure_rate=0.1),
    NotificationChannel.SMS:   MockSMSProvider(failure_rate=0.1),
    NotificationChannel.PUSH:  MockPushProvider(failure_rate=0.1),
}

# queue and workers
queue   = QueueService()
worker  = NotificationWorker(queue=queue, providers=providers)

# rabbitmq consumer — also handles retry events from retry queue
# no polling reaper needed — RabbitMQ TTL fires retries precisely
rabbitmq = RabbitMQHandler(queue_service=queue)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting notification service...")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await worker.start()
    await rabbitmq.start()

    logger.info("All components started — workers running, RabbitMQ TTL handles retries")
    yield

    logger.info("Shutting down notification service...")
    await worker.stop()
    await rabbitmq.stop()
    await queue.close_rabbitmq()
    await engine.dispose()


app = FastAPI(
    title="Notification Service",
    description="High throughput notification service for Order, Payment and Shipping events",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(notification_router)
register_exception_handlers(app)


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok"}


@app.get("/health/providers", tags=["Health"])
async def health_providers():
    return {
        "email": "up" if await providers[NotificationChannel.EMAIL].health_check() else "down",
        "sms":   "up" if await providers[NotificationChannel.SMS].health_check() else "down",
        "push":  "up" if await providers[NotificationChannel.PUSH].health_check() else "down",
    }


@app.get("/metrics", tags=["Metrics"])
async def metrics():
    return {
        "queue_depth": await queue.depth(),
    }