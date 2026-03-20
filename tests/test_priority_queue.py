import pytest
import time
import asyncio
from unittest.mock import AsyncMock, patch
from app.services.queue_service import QueueService


@pytest.mark.asyncio
async def test_otp_processed_before_marketing():
    """OTP (priority=1) must always come out before marketing (priority=4)"""

    queue = QueueService()

    with patch.object(queue, "redis") as mock_redis:
        enqueue_calls = []

        async def mock_zadd(key, mapping, nx=False):
            enqueue_calls.append(mapping)
            return 1

        mock_redis.zadd = mock_zadd

        await queue.enqueue(notification_id=1, priority=4)
        await queue.enqueue(notification_id=2, priority=1)

        otp_score      = list(enqueue_calls[1].values())[0]
        marketing_score = list(enqueue_calls[0].values())[0]

        assert otp_score < marketing_score, \
            f"OTP score {otp_score} should be less than marketing score {marketing_score}"


@pytest.mark.asyncio
async def test_fifo_within_same_priority():
    """Within same priority, older notifications should have lower score"""

    queue = QueueService()

    with patch.object(queue, "redis") as mock_redis:
        scores = []

        async def mock_zadd(key, mapping, nx=False):
            scores.append(list(mapping.values())[0])
            return 1

        mock_redis.zadd = mock_zadd

        await queue.enqueue(notification_id=1, priority=2)
        await asyncio.sleep(0.01)
        await queue.enqueue(notification_id=2, priority=2)

        assert scores[0] < scores[1], \
            "Earlier enqueued notification should have lower score"


@pytest.mark.asyncio
async def test_score_formula():
    """Score must be priority * 10^12 + timestamp_ms"""

    queue = QueueService()

    with patch.object(queue, "redis") as mock_redis:
        captured_score = None

        async def mock_zadd(key, mapping, nx=False):
            nonlocal captured_score
            captured_score = list(mapping.values())[0]
            return 1

        mock_redis.zadd = mock_zadd

        before = int(time.time() * 1000)
        await queue.enqueue(notification_id=1, priority=1)
        after = int(time.time() * 1000)

        priority_component = 1 * (10 ** 12)
        timestamp_component = captured_score - priority_component

        # timestamp component should be between before and after
        assert before <= timestamp_component <= after + 100, \
            f"Timestamp component {timestamp_component} should be between {before} and {after}"

        # score should start with priority component
        assert captured_score >= priority_component, \
            f"Score {captured_score} should be >= priority component {priority_component}"