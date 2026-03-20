import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.models.notification import (
    NotificationStatus,
    NotificationChannel,
    NotificationErrorCode,
    EventType,
)
from app.providers.base import ProviderResult
from app.services.dispatch_service import DispatchService


def make_notification(
    channel=NotificationChannel.SMS,
    event_type=EventType.PAYMENT_FAILED,
    retry_count=0,
):
    n = MagicMock()
    n.id = 1
    n.channel = channel.value
    n.event_type = event_type.value
    n.recipient = "+919876543210"
    n.content = {"body": "Payment failed"}
    n.retry_count = retry_count
    n.priority = 2
    return n


@pytest.mark.asyncio
async def test_sms_down_does_not_affect_email():
    """When SMS provider is down, email should still work independently"""

    email_provider = AsyncMock()
    email_provider.health_check = AsyncMock(return_value=True)
    email_provider.send = AsyncMock(return_value=ProviderResult(
        success=True, external_id="mock-email-123"
    ))

    sms_provider = AsyncMock()
    sms_provider.health_check = AsyncMock(return_value=False)  # SMS is DOWN

    providers = {
        NotificationChannel.EMAIL: email_provider,
        NotificationChannel.SMS: sms_provider,
    }

    mock_db = AsyncMock()
    mock_repo = AsyncMock()
    mock_queue = AsyncMock()

    # test SMS notification
    sms_notification = make_notification(channel=NotificationChannel.SMS)
    mock_repo.get_by_id = AsyncMock(return_value=sms_notification)
    mock_repo.update_status = AsyncMock(return_value=sms_notification)

    with patch("app.services.dispatch_service.NotificationRepository", return_value=mock_repo):
        service = DispatchService(db=mock_db, providers=providers, queue=mock_queue)
        await service.dispatch(1)

    # SMS should be retrying, not failed
    update_calls = mock_repo.update_status.call_args_list
    final_status = update_calls[-1][0][1]
    assert final_status == NotificationStatus.RETRYING, \
        "SMS should be RETRYING when provider is down"

    # email provider should never have been touched
    email_provider.send.assert_not_called()


@pytest.mark.asyncio
async def test_non_retryable_error_fails_immediately():
    """Invalid recipient should fail immediately without retrying"""

    sms_provider = AsyncMock()
    sms_provider.health_check = AsyncMock(return_value=True)
    sms_provider.send = AsyncMock(return_value=ProviderResult(
        success=False,
        error_code=NotificationErrorCode.INVALID_RECIPIENT.value,
        error_message="Invalid phone number"
    ))

    providers = {NotificationChannel.SMS: sms_provider}

    mock_db = AsyncMock()
    mock_repo = AsyncMock()
    mock_queue = AsyncMock()

    notification = make_notification(channel=NotificationChannel.SMS)
    mock_repo.get_by_id = AsyncMock(return_value=notification)
    mock_repo.update_status = AsyncMock(return_value=notification)

    with patch("app.services.dispatch_service.NotificationRepository", return_value=mock_repo):
        service = DispatchService(db=mock_db, providers=providers, queue=mock_queue)
        await service.dispatch(1)

    update_calls = mock_repo.update_status.call_args_list
    final_status = update_calls[-1][0][1]
    assert final_status == NotificationStatus.FAILED, \
        "Invalid recipient should immediately FAIL without retry"


@pytest.mark.asyncio
async def test_retry_count_increments():
    """retry_count should increment on each retry"""

    sms_provider = AsyncMock()
    sms_provider.health_check = AsyncMock(return_value=True)
    sms_provider.send = AsyncMock(return_value=ProviderResult(
        success=False,
        error_code=NotificationErrorCode.TIMEOUT.value,
        error_message="Timeout"
    ))

    providers = {NotificationChannel.SMS: sms_provider}
    mock_db = AsyncMock()
    mock_repo = AsyncMock()
    mock_queue = AsyncMock()

    notification = make_notification(channel=NotificationChannel.SMS, retry_count=0)
    mock_repo.get_by_id = AsyncMock(return_value=notification)
    mock_repo.update_status = AsyncMock(return_value=notification)

    with patch("app.services.dispatch_service.NotificationRepository", return_value=mock_repo):
        service = DispatchService(db=mock_db, providers=providers, queue=mock_queue)
        await service.dispatch(1)

    update_calls = mock_repo.update_status.call_args_list
    retry_kwargs = update_calls[-1][1]
    assert retry_kwargs.get("retry_count") == 1, \
        "retry_count should be incremented to 1"


@pytest.mark.asyncio
async def test_exhausted_retries_go_to_failed():
    """After max retries exhausted notification should be permanently FAILED"""

    sms_provider = AsyncMock()
    sms_provider.health_check = AsyncMock(return_value=True)
    sms_provider.send = AsyncMock(return_value=ProviderResult(
        success=False,
        error_code=NotificationErrorCode.TIMEOUT.value,
        error_message="Timeout"
    ))

    providers = {NotificationChannel.SMS: sms_provider}
    mock_db = AsyncMock()
    mock_repo = AsyncMock()
    mock_queue = AsyncMock()

    # OTP max retries is 3 — set retry_count to 3 (already exhausted)
    notification = make_notification(
        channel=NotificationChannel.SMS,
        event_type=EventType.PAYMENT_OTP_REQUESTED,
        retry_count=3,
    )
    mock_repo.get_by_id = AsyncMock(return_value=notification)
    mock_repo.update_status = AsyncMock(return_value=notification)

    with patch("app.services.dispatch_service.NotificationRepository", return_value=mock_repo), \
         patch("app.services.dispatch_service.DispatchService._send_to_dlq", new_callable=AsyncMock):
        service = DispatchService(db=mock_db, providers=providers, queue=mock_queue)
        await service.dispatch(1)

    update_calls = mock_repo.update_status.call_args_list
    final_status = update_calls[-1][0][1]
    assert final_status == NotificationStatus.FAILED, \
        "Exhausted retries should result in FAILED status"