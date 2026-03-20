from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from app.models.notification import NotificationChannel


@dataclass
class ProviderResult:
    success: bool
    external_id: Optional[str] = None
    error_code: Optional[int] = None
    error_message: Optional[str] = None


class BaseProvider(ABC):
    """
    Abstract base class every provider must implement.
    New channels (WhatsApp, Slack) just implement these two methods.
    No other code changes needed anywhere else.
    """

    @property
    @abstractmethod
    def channel(self) -> NotificationChannel:
        """Which channel this provider handles"""

    @abstractmethod
    async def send(self, recipient: str, content: dict) -> ProviderResult:
        """
        Attempt delivery.
        Must NEVER raise — always return a ProviderResult.
        """

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if provider is reachable"""