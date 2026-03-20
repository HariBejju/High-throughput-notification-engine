import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.schemas.notification_request import NotificationCreate, RecipientInfo


def make_payload(idempotency_key="order-001-order_created"):
    return NotificationCreate(
        idempotency_key=idempotency_key,
        source_service="order",
        event_type="order_created",
        priority="high",
        recipient=RecipientInfo(
            email="john@gmail.com",
            device_token="fcm-token-abc"
        ),
        content={
            "email": {"subject": "Order confirmed", "body": "Your order is confirmed."},
            "push": {"title": "Order Confirmed", "body": "Your order is confirmed."}
        }
    )


@pytest.mark.asyncio
async def test_first_request_is_processed():
    """First request with a new idempotency key should be processed"""
    from app.managers.notification_manager import NotificationManager

    mock_db = AsyncMock()

    with patch("app.managers.notification_manager.redis_client") as mock_redis, \
         patch("app.managers.notification_manager.queue_service") as mock_queue, \
         patch("app.managers.notification_manager.NotificationRepository") as mock_repo_class:

        mock_redis.setnx = AsyncMock(return_value=True)
        mock_redis.expire = AsyncMock()

        mock_notification = MagicMock()
        mock_notification.id = 1
        mock_notification.priority = 2

        mock_repo = AsyncMock()
        mock_repo.create = AsyncMock(return_value=mock_notification)
        mock_repo_class.return_value = mock_repo

        mock_queue.enqueue = AsyncMock(return_value=True)

        manager = NotificationManager(mock_db)
        notifications, is_duplicate = await manager.create_notification(make_payload())

        assert is_duplicate is False
        assert len(notifications) > 0
        mock_redis.setnx.assert_called_once()


@pytest.mark.asyncio
async def test_duplicate_request_is_blocked():
    """Second request with same idempotency key should be blocked by Redis"""
    from app.managers.notification_manager import NotificationManager

    mock_db = AsyncMock()

    with patch("app.managers.notification_manager.redis_client") as mock_redis:
        # Redis returns False — key already exists
        mock_redis.setnx = AsyncMock(return_value=False)

        manager = NotificationManager(mock_db)
        notifications, is_duplicate = await manager.create_notification(make_payload())

        assert is_duplicate is True
        assert notifications == []


@pytest.mark.asyncio
async def test_different_keys_both_processed():
    """Two requests with different idempotency keys should both be processed"""
    from app.managers.notification_manager import NotificationManager

    mock_db = AsyncMock()

    with patch("app.managers.notification_manager.redis_client") as mock_redis, \
         patch("app.managers.notification_manager.queue_service") as mock_queue, \
         patch("app.managers.notification_manager.NotificationRepository") as mock_repo_class:

        mock_redis.setnx = AsyncMock(return_value=True)
        mock_redis.expire = AsyncMock()

        mock_notification = MagicMock()
        mock_notification.id = 1
        mock_notification.priority = 2

        mock_repo = AsyncMock()
        mock_repo.create = AsyncMock(return_value=mock_notification)
        mock_repo_class.return_value = mock_repo
        mock_queue.enqueue = AsyncMock(return_value=True)

        manager = NotificationManager(mock_db)

        _, is_dup1 = await manager.create_notification(make_payload("key-001"))
        _, is_dup2 = await manager.create_notification(make_payload("key-002"))

        assert is_dup1 is False
        assert is_dup2 is False