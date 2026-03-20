from app.models.notification import EventType, NotificationChannel

EMAIL = NotificationChannel.EMAIL
SMS   = NotificationChannel.SMS
PUSH  = NotificationChannel.PUSH

# Maps each event type to the channels it should notify
# To add a new event — just add a new entry here, no other code changes needed
EVENT_CHANNEL_MAP = {
    EventType.ORDER_CREATED:         [EMAIL, PUSH],
    EventType.ORDER_CANCELLED:       [EMAIL, PUSH],
    EventType.PAYMENT_CONFIRMED:     [EMAIL, PUSH],
    EventType.PAYMENT_FAILED:        [EMAIL, SMS, PUSH],
    EventType.PAYMENT_OTP_REQUESTED: [SMS],
    EventType.SHIPMENT_DISPATCHED:   [EMAIL, PUSH],
    EventType.SHIPMENT_DELIVERED:    [EMAIL, PUSH],
    EventType.SHIPMENT_DELAYED:      [EMAIL, SMS],
}

# Maps each channel to which recipient field it needs
CHANNEL_RECIPIENT_FIELD = {
    EMAIL: "email",
    SMS:   "phone",
    PUSH:  "device_token",
}