"""Event system unit tests."""

from sentinel.core.events import EventType, SentinelEvent


def test_sentinel_event_creation():
    event = SentinelEvent(
        type=EventType.CLIENT_ENTERED,
        camera_id="cam-1",
        location_id="salon-1",
        tenant_id="tenant-abc",
        track_id="track-1",
        confidence=0.95,
        payload={"test": True},
        timestamp_ms=1700000000000,
    )
    assert event.type == EventType.CLIENT_ENTERED
    assert event.tenant_id == "tenant-abc"
    assert event.id  # auto-generated UUID


def test_event_types_exist():
    assert EventType.CLIENT_ENTERED
    assert EventType.FACE_IDENTIFIED
    assert EventType.ZONE_ENTERED
    assert EventType.ZONE_EXITED
    assert EventType.STAFF_ABSENT
    assert EventType.CLIENT_UNATTENDED
    assert EventType.FRAUD_ALERT


def test_event_default_tenant():
    event = SentinelEvent(
        type=EventType.CLIENT_ENTERED,
        camera_id="cam-1",
        location_id="loc-1",
    )
    assert event.tenant_id == "legacy"


async def _connect_with_test_redis(monkeypatch, error=None):
    import asyncio
    from unittest.mock import AsyncMock, Mock

    from sentinel.core import events

    fake_url = "redis://user:fake-test-secret@redis.example/0"
    bus = events.EventBus()
    bus._redis_url = fake_url
    subscription = Mock()
    subscription.subscribe = AsyncMock(side_effect=error)
    redis = Mock()
    redis.pubsub.return_value = subscription
    monkeypatch.setattr(events.aioredis, "from_url", Mock(return_value=redis))
    dispatch = asyncio.Event()
    monkeypatch.setattr(bus, "_dispatch_loop", dispatch.wait)
    await bus.connect()


def test_redis_connect_never_logs_url(monkeypatch):
    import asyncio

    from loguru import logger

    messages = []
    sink = logger.add(messages.append)
    try:
        asyncio.run(_connect_with_test_redis(monkeypatch))
    finally:
        logger.remove(sink)
    assert any("connected to Redis" in message for message in messages)
    assert all("fake-test-secret" not in message for message in messages)


def test_redis_connect_failure_hides_driver_exception(monkeypatch):
    import asyncio
    import traceback

    import pytest

    driver_error = ValueError("fake-test-secret")
    with pytest.raises(RuntimeError, match="Cannot connect to Redis") as error:
        asyncio.run(_connect_with_test_redis(monkeypatch, driver_error))
    assert "fake-test-secret" not in "".join(traceback.format_exception(error.value))
