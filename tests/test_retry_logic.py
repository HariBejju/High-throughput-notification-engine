import pytest
from app.services.dispatch_service import get_retry_delay


def test_exponential_backoff_formula():
    """Verify exponential backoff doubles each retry"""
    assert get_retry_delay(1, 86400, use_jitter=False) == 30
    assert get_retry_delay(2, 86400, use_jitter=False) == 60
    assert get_retry_delay(3, 86400, use_jitter=False) == 120
    assert get_retry_delay(4, 86400, use_jitter=False) == 240
    assert get_retry_delay(5, 86400, use_jitter=False) == 480


def test_delay_capped_at_max():
    """Delay should never exceed max_delay"""
    max_delay = 30  # OTP max delay
    for retry in range(1, 10):
        delay = get_retry_delay(retry, max_delay, use_jitter=False)
        assert delay <= max_delay, \
            f"Delay {delay} exceeds max_delay {max_delay} at retry {retry}"


def test_jitter_within_window():
    """Jitter should produce delay between 1 and max window"""
    for _ in range(100):
        delay = get_retry_delay(1, 86400, use_jitter=True)
        assert 1 <= delay <= 30, \
            f"Jittered delay {delay} should be between 1 and 30"


def test_no_jitter_for_otp():
    """OTP should use fixed delay — no jitter"""
    from app.services.dispatch_service import RETRY_CONFIG
    from app.models.notification import EventType
    config = RETRY_CONFIG[EventType.PAYMENT_OTP_REQUESTED]
    assert config["use_jitter"] is False


def test_jitter_for_bulk_notifications():
    """Bulk notifications should use jitter"""
    from app.services.dispatch_service import RETRY_CONFIG
    from app.models.notification import EventType
    assert RETRY_CONFIG[EventType.ORDER_CREATED]["use_jitter"] is True
    assert RETRY_CONFIG[EventType.PAYMENT_FAILED]["use_jitter"] is True
    assert RETRY_CONFIG[EventType.SHIPMENT_DISPATCHED]["use_jitter"] is True


def test_otp_max_delay_is_30_seconds():
    """OTP retry delay should be capped at 30 seconds"""
    from app.services.dispatch_service import RETRY_CONFIG
    from app.models.notification import EventType
    config = RETRY_CONFIG[EventType.PAYMENT_OTP_REQUESTED]
    assert config["max_delay"] == 30


def test_otp_max_retries_is_3():
    """OTP should only retry 3 times"""
    from app.services.dispatch_service import RETRY_CONFIG
    from app.models.notification import EventType
    config = RETRY_CONFIG[EventType.PAYMENT_OTP_REQUESTED]
    assert config["max_retries"] == 3


def test_order_max_retries_is_10():
    """Order notifications should retry up to 10 times"""
    from app.services.dispatch_service import RETRY_CONFIG
    from app.models.notification import EventType
    config = RETRY_CONFIG[EventType.ORDER_CREATED]
    assert config["max_retries"] == 10


def test_delay_increases_each_retry():
    """Each retry should have longer delay than previous (no jitter)"""
    max_delay = 86400
    prev_delay = 0
    for retry in range(1, 8):
        delay = get_retry_delay(retry, max_delay, use_jitter=False)
        if prev_delay < max_delay:
            assert delay > prev_delay, \
                f"Delay should increase at retry {retry}"
        prev_delay = delay