import pytest
from app.services.dispatch_service import get_retry_delay


def test_exponential_backoff_formula():
    """Verify exponential backoff doubles each retry"""
    assert get_retry_delay(1, 86400) == 30
    assert get_retry_delay(2, 86400) == 60
    assert get_retry_delay(3, 86400) == 120
    assert get_retry_delay(4, 86400) == 240
    assert get_retry_delay(5, 86400) == 480


def test_delay_capped_at_max():
    """Delay should never exceed max_delay"""
    max_delay = 300  # 5 minutes for OTP
    for retry in range(1, 10):
        delay = get_retry_delay(retry, max_delay)
        assert delay <= max_delay, \
            f"Delay {delay} exceeds max_delay {max_delay} at retry {retry}"


def test_otp_max_delay_is_5_minutes():
    """OTP retry delay should be capped at 5 minutes"""
    from app.services.dispatch_service import RETRY_CONFIG
    from app.models.notification import EventType
    config = RETRY_CONFIG[EventType.PAYMENT_OTP_REQUESTED]
    assert config["max_delay"] == 300


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
    """Each retry should have a longer delay than the previous"""
    max_delay = 86400
    prev_delay = 0
    for retry in range(1, 8):
        delay = get_retry_delay(retry, max_delay)
        if prev_delay < max_delay:
            assert delay > prev_delay, \
                f"Delay should increase at retry {retry}"
        prev_delay = delay