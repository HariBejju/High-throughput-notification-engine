import pytest
from app.event_channel_map import EVENT_CHANNEL_MAP
from app.models.notification import EventType, NotificationChannel


def test_payment_failed_has_all_three_channels():
    """payment_failed should notify via email, sms and push"""
    channels = EVENT_CHANNEL_MAP[EventType.PAYMENT_FAILED]
    assert NotificationChannel.EMAIL in channels
    assert NotificationChannel.SMS in channels
    assert NotificationChannel.PUSH in channels


def test_otp_only_sms():
    """OTP should only go via SMS"""
    channels = EVENT_CHANNEL_MAP[EventType.PAYMENT_OTP_REQUESTED]
    assert channels == [NotificationChannel.SMS]
    assert NotificationChannel.EMAIL not in channels
    assert NotificationChannel.PUSH not in channels


def test_order_created_no_sms():
    """Order created should not send SMS"""
    channels = EVENT_CHANNEL_MAP[EventType.ORDER_CREATED]
    assert NotificationChannel.SMS not in channels
    assert NotificationChannel.EMAIL in channels
    assert NotificationChannel.PUSH in channels


def test_all_event_types_have_mapping():
    """Every event type must have at least one channel mapped"""
    for event_type in EventType:
        channels = EVENT_CHANNEL_MAP.get(event_type, [])
        assert len(channels) > 0, \
            f"EventType.{event_type.name} has no channel mapping"


def test_no_empty_channel_lists():
    """No event type should map to an empty channel list"""
    for event_type, channels in EVENT_CHANNEL_MAP.items():
        assert len(channels) > 0, \
            f"EventType.{event_type.name} maps to empty channel list"