import asyncio
import random
import uuid
import logging

from app.models.notification import NotificationChannel, NotificationErrorCode
from app.providers.base import BaseProvider, ProviderResult

logger = logging.getLogger(__name__)


class MockPushProvider(BaseProvider):
    """
    Mock Push provider — simulates FCM/APNs.
    85% success, 10% timeout, 5% invalid token.
    Replace send() with real FCM call in production.
    """

    def __init__(self, failure_rate: float = 0.1):
        self.failure_rate = failure_rate
        self._healthy = True

    @property
    def channel(self) -> NotificationChannel:
        return NotificationChannel.PUSH

    async def send(self, recipient: str, content: dict) -> ProviderResult:
        try:
            await asyncio.sleep(0.05)

            if not self._healthy:
                raise ConnectionError("Push provider is down")

            # simulate 5% invalid token rate
            if random.random() < 0.05:
                return ProviderResult(
                    success=False,
                    error_code=NotificationErrorCode.INVALID_TOKEN,
                    error_message="Device token is expired or invalid",
                )

            if random.random() < self.failure_rate:
                raise TimeoutError("Push provider timeout")

            external_id = f"mock-push-{uuid.uuid4().hex[:8]}"
            logger.info("PUSH sent to %s id=%s", recipient, external_id)

            return ProviderResult(success=True, external_id=external_id)

        except TimeoutError:
            return ProviderResult(
                success=False,
                error_code=NotificationErrorCode.TIMEOUT,
                error_message="Push provider timeout",
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
        self._healthy = False
        logger.warning("Push provider simulated downtime")

    def simulate_recovery(self):
        self._healthy = True
        logger.info("Push provider simulated recovery")