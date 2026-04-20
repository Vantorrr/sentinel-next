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
