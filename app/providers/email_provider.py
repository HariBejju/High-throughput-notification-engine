import asyncio
import random
import uuid
import logging

from app.models.notification import NotificationChannel, NotificationErrorCode
from app.providers.base import BaseProvider, ProviderResult

logger = logging.getLogger(__name__)


class MockEmailProvider(BaseProvider):
    """
    Mock Email provider — simulates SES/SMTP.
    90% success rate, 10% random failure.
    Replace send() with real SES call in production.
    """

    def __init__(self, failure_rate: float = 0.1):
        self.failure_rate = failure_rate
        self._healthy = True

    @property
    def channel(self) -> NotificationChannel:
        return NotificationChannel.EMAIL

    async def send(self, recipient: str, content: dict) -> ProviderResult:
        try:
            # simulate network latency
            await asyncio.sleep(0.1)

            if not self._healthy:
                raise ConnectionError("Email provider is down")

            if random.random() < self.failure_rate:
                raise TimeoutError("Email provider timeout")

            external_id = f"mock-email-{uuid.uuid4().hex[:8]}"
            logger.info("EMAIL sent to %s id=%s", recipient, external_id)

            return ProviderResult(success=True, external_id=external_id)

        except TimeoutError:
            return ProviderResult(
                success=False,
                error_code=NotificationErrorCode.TIMEOUT,
                error_message="Email provider timeout",
            )
        except ConnectionError as e:
            return ProviderResult(
                success=False,
                error_code=NotificationErrorCode.PROVIDER_DOWN,
                error_message=str(e),
            )
        except Exception as e:
            return ProviderResult(
                success=False,
                error_code=NotificationErrorCode.UNKNOWN,
                error_message=str(e),
            )

    async def health_check(self) -> bool:
        return self._healthy

    def simulate_downtime(self):
        """Call this to simulate provider going down — useful for testing"""
        self._healthy = False
        logger.warning("Email provider simulated downtime")

    def simulate_recovery(self):
        """Call this to simulate provider recovering"""
        self._healthy = True
        logger.info("Email provider simulated recovery")