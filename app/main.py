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
from app.workers.retry_reaper import RetryReaper

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

# queue, workers, reaper
queue   = QueueService()
worker  = NotificationWorker(queue=queue, providers=providers)
reaper  = RetryReaper(queue=queue)

# rabbitmq consumer
rabbitmq = RabbitMQHandler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting notification service...")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await worker.start()
    await reaper.start()
    await rabbitmq.start()

    logger.info("All components started successfully")
    yield

    logger.info("Shutting down notification service...")
    await worker.stop()
    await reaper.stop()
    await rabbitmq.stop()
    await engine.dispose()


app = FastAPI(
    title="Notification Service",
    description="High throughput notification service for Order, Payment and Shipping events",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(notification_router)
register_exception_handlers(app)


@app.get("/health")
async def health():
    checks = {}
    
    # check DB
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "down"
    
    # check Redis
    try:
        await redis_client.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "down"
    
    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": overall, "checks": checks}


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