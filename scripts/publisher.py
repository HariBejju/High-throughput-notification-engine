"""
Publisher script — simulates Order, Payment, Shipping microservices
publishing events to RabbitMQ.

Usage:
    python scripts/publisher.py              ──► publishes all sample events
    python scripts/publisher.py --load-test  ──► publishes 100 events rapidly
"""
import asyncio
import json
import sys
import uuid
import argparse
from datetime import datetime

import aio_pika

RABBITMQ_URL  = "amqp://notif_user:notif_pass@localhost:5672/"
EXCHANGE_NAME = "notification.exchange"

# sample events simulating real microservice events
SAMPLE_EVENTS = [
    {
        "routing_key": "order.created",
        "event": {
            "idempotency_key": f"order-001-order_created-{uuid.uuid4().hex[:8]}",
            "source_service": "order",
            "event_type": "order_created",
            "priority": "high",
            "recipient": {
                "email": "john@gmail.com",
                "device_token": "fcm-token-abc123"
            },
            "content": {
                "email": {
                    "subject": "Order Confirmed!",
                    "body": "Hi John, your order #001 has been confirmed."
                },
                "push": {
                    "title": "Order Confirmed",
                    "body": "Your order #001 is confirmed."
                }
            }
        }
    },
    {
        "routing_key": "payment.confirmed",
        "event": {
            "idempotency_key": f"payment-001-payment_confirmed-{uuid.uuid4().hex[:8]}",
            "source_service": "payment",
            "event_type": "payment_confirmed",
            "priority": "high",
            "recipient": {
                "email": "john@gmail.com",
                "device_token": "fcm-token-abc123"
            },
            "content": {
                "email": {
                    "subject": "Payment Successful",
                    "body": "Your payment of ₹1299 was successful."
                },
                "push": {
                    "title": "Payment Successful",
                    "body": "₹1299 payment confirmed."
                }
            }
        }
    },
    {
        "routing_key": "payment.failed",
        "event": {
            "idempotency_key": f"payment-002-payment_failed-{uuid.uuid4().hex[:8]}",
            "source_service": "payment",
            "event_type": "payment_failed",
            "priority": "high",
            "recipient": {
                "email": "john@gmail.com",
                "phone": "+919876543210",
                "device_token": "fcm-token-abc123"
            },
            "content": {
                "email": {
                    "subject": "Payment Failed",
                    "body": "Your payment of ₹1299 failed. Please retry."
                },
                "sms": {
                    "body": "Payment of ₹1299 failed. Retry now."
                },
                "push": {
                    "title": "Payment Failed",
                    "body": "Your payment failed. Tap to retry."
                }
            }
        }
    },
    {
        "routing_key": "payment.otp",
        "event": {
            "idempotency_key": f"payment-003-payment_otp_requested-{uuid.uuid4().hex[:8]}",
            "source_service": "payment",
            "event_type": "payment_otp_requested",
            "priority": "critical",
            "recipient": {
                "phone": "+919876543210"
            },
            "content": {
                "sms": {
                    "body": "Your OTP is 123456. Valid for 5 minutes. Do not share."
                }
            }
        }
    },
    {
        "routing_key": "shipping.dispatched",
        "event": {
            "idempotency_key": f"shipping-001-shipment_dispatched-{uuid.uuid4().hex[:8]}",
            "source_service": "shipping",
            "event_type": "shipment_dispatched",
            "priority": "medium",
            "recipient": {
                "email": "john@gmail.com",
                "device_token": "fcm-token-abc123"
            },
            "content": {
                "email": {
                    "subject": "Your order is on the way!",
                    "body": "Your order #001 has been dispatched. Track: TRK123456"
                },
                "push": {
                    "title": "Order Dispatched",
                    "body": "Your order is on the way!"
                }
            }
        }
    },
]


async def publish_event(channel, exchange, routing_key: str, event: dict):
    """Publish a single event to RabbitMQ"""
    body = json.dumps(event).encode()

    await exchange.publish(
        aio_pika.Message(
            body=body,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            content_type="application/json",
        ),
        routing_key=routing_key,
    )
    print(f"  ✓ Published {event['event_type']} routing_key={routing_key}")


async def run_sample_events():
    """Publish all sample events"""
    print("\n── Publishing sample events ──────────────────")

    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(
            "notification.exchange",
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )

        for item in SAMPLE_EVENTS:
            await publish_event(
                channel,
                exchange,
                item["routing_key"],
                item["event"],
            )
            await asyncio.sleep(0.5)

    print("\n── All events published ──────────────────────")
    print("Check GET /notifications to see them processed")


async def run_load_test(count: int = 100):
    """Publish N events rapidly for load testing"""
    print(f"\n── Load test: publishing {count} events ──────")

    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(
            "notification.exchange",
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )

        start = datetime.utcnow()

        for i in range(count):
            event = {
                "idempotency_key": f"load-test-order-{uuid.uuid4().hex[:8]}",
                "source_service": "order",
                "event_type": "order_created",
                "priority": "medium",
                "recipient": {
                    "email": f"user{i}@gmail.com",
                    "device_token": f"fcm-token-{uuid.uuid4().hex[:8]}"
                },
                "content": {
                    "email": {
                        "subject": f"Order #{i} Confirmed",
                        "body": f"Your order #{i} has been confirmed."
                    },
                    "push": {
                        "title": "Order Confirmed",
                        "body": f"Order #{i} confirmed."
                    }
                }
            }
            await publish_event(channel, exchange, "order.created", event)

        elapsed = (datetime.utcnow() - start).total_seconds()
        rate = count / elapsed

    print(f"\n── Load test complete ────────────────────────")
    print(f"  Published : {count} events")
    print(f"  Time      : {elapsed:.2f} seconds")
    print(f"  Rate      : {rate:.1f} events/sec")
    print(f"  Projected : {rate * 60:.0f} events/min")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Notification Service Publisher")
    parser.add_argument("--load-test", action="store_true", help="Run load test")
    parser.add_argument("--count", type=int, default=100, help="Number of events for load test")
    args = parser.parse_args()

    if args.load_test:
        asyncio.run(run_load_test(args.count))
    else:
        asyncio.run(run_sample_events())