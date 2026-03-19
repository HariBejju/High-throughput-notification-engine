import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import engine, Base
from app.controllers.notification_controller import router as notification_router
from app.handlers.exception_handler import register_exception_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    logger.info("Starting notification service...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # shutdown
    logger.info("Shutting down notification service...")
    await engine.dispose()


app = FastAPI(
    title="Notification Service",
    description="High throughput notification service for Order, Payment and Shipping events",
    version="1.0.0",
    lifespan=lifespan,
)

# register routers
app.include_router(notification_router)

# register exception handlers
register_exception_handlers(app)


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok"}