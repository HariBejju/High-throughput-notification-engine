import asyncio
import random
import uuid
import logging

from app.models.notification import NotificationChannel, NotificationErrorCode
from app.providers.base import BaseProvider, ProviderResult

logger = logging.getLogger(__name__)


class MockSMSProvider(BaseProvider):
    """
    Mock SMS provider — simulates Twilio.
    90% success rate, 10% random failure.
    Can simulate downtime to test partial failure handling.
    Replace send() with real Twilio call in production.
    """

    def __init__(self, failure_rate: float = 0.1):
        self.failure_rate = failure_rate
        self._healthy = True

    @property
    def channel(self) -> NotificationChannel:
        return NotificationChannel.SMS

    async def send(self, recipient: str, content: dict) -> ProviderResult:
        try:
            await asyncio.sleep(0.08)

            if not self._healthy:
                raise ConnectionError("SMS provider is down")

            # validate phone number format
            if not recipient.startswith("+"):
                return ProviderResult(
                    success=False,
                    error_code=NotificationErrorCode.INVALID_RECIPIENT,
                    error_message="Invalid phone number format — must start with +"
                )

            if random.random() < self.failure_rate:
                raise TimeoutError("SMS provider timeout")

            external_id = f"mock-sms-{uuid.uuid4().hex[:8]}"
            logger.info("SMS sent to %s id=%s", recipient, external_id)

            return ProviderResult(success=True, external_id=external_id)

        except TimeoutError:
            return ProviderResult(
                success=False,
                error_code=NotificationErrorCode.TIMEOUT,
                error_message="SMS provider timeout",
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
        logger.warning("SMS provider simulated downtime")

    def simulate_recovery(self):
        self._healthy = True
        logger.info("SMS provider simulated recovery")