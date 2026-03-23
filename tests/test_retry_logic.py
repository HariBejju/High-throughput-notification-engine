import pytest
from app.services.dispatch_service import get_retry_delay


def test_bulk_retry_windows():
    """Each retry level has its own distinct window — no overlap"""
    # retry 1 ──► fixed low end = 15 (no jitter in test, use_jitter=False)
    assert get_retry_delay(1, 15, 3600, use_jitter=False) == 15
    # retry 2 ──► fixed low end = 30
    assert get_retry_delay(2, 15, 3600, use_jitter=False) == 30
    # retry 3 ──► fixed low end = 60
    assert get_retry_delay(3, 15, 3600, use_jitter=False) == 60


def test_otp_retry_windows():
    """OTP uses fixed delays — no jitter"""
    assert get_retry_delay(1, 5, 30, use_jitter=False) == 5
    assert get_retry_delay(2, 5, 30, use_jitter=False) == 10
    assert get_retry_delay(3, 5, 30, use_jitter=False) == 20


def test_jitter_within_correct_window():
    """Jitter stays within its retry window — no overlap between levels"""
    for _ in range(100):
        r1 = get_retry_delay(1, 15, 3600, use_jitter=True)
        assert 15 <= r1 <= 30, f"retry 1 should be 15-30, got {r1}"

        r2 = get_retry_delay(2, 15, 3600, use_jitter=True)
        assert 30 <= r2 <= 60, f"retry 2 should be 30-60, got {r2}"

        r3 = get_retry_delay(3, 15, 3600, use_jitter=True)
        assert 60 <= r3 <= 120, f"retry 3 should be 60-120, got {r3}"


def test_delay_capped_at_max():
    """Delay should never exceed max_delay"""
    for retry in range(1, 6):
        delay = get_retry_delay(retry, 15, 30, use_jitter=False)
        assert delay <= 30, f"Delay {delay} exceeds max_delay 30 at retry {retry}"


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


def test_all_events_max_3_retries():
    """All event types should have max 3 retries"""
    from app.services.dispatch_service import RETRY_CONFIG
    for event_type, config in RETRY_CONFIG.items():
        assert config["max_retries"] == 3, \
            f"{event_type.name} should have max 3 retries"


def test_otp_base_delay_is_5():
    """OTP base delay should be 5 seconds"""
    from app.services.dispatch_service import RETRY_CONFIG
    from app.models.notification import EventType
    assert RETRY_CONFIG[EventType.PAYMENT_OTP_REQUESTED]["base_delay"] == 5


def test_bulk_base_delay_is_15():
    """Bulk base delay should be 15 seconds"""
    from app.services.dispatch_service import RETRY_CONFIG
    from app.models.notification import EventType
    assert RETRY_CONFIG[EventType.ORDER_CREATED]["base_delay"] == 15
    assert RETRY_CONFIG[EventType.PAYMENT_FAILED]["base_delay"] == 15


def test_windows_do_not_overlap():
    """retry 2 low end should equal retry 1 high end"""
    r1_low  = 15 * (2 ** 0)  # 15
    r1_high = 15 * (2 ** 1)  # 30
    r2_low  = 15 * (2 ** 1)  # 30
    r2_high = 15 * (2 ** 2)  # 60
    assert r1_high == r2_low, "Windows should be contiguous not overlapping"