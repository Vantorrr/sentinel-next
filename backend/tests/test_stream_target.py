"""Stream URL classification: no silent placeholder success, no LAN rewrite."""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock

import pytest

from sentinel.pipeline.camera import CameraConfig, CameraReader
from sentinel.pipeline.manager import PipelineManager
from sentinel.pipeline.stream_target import (
    assess_hik_stream,
    caller_may_see_camera,
    classify_stream_url,
    hik_upsert_action,
    redact_stream_url,
    redact_text,
)
from sentinel.services.hikconnect.client import HikConnectClient

_SECRET = "s3cret-value"
_PLACEHOLDER = "rtsp://admin@<LOCAL_IP>:554/Streaming/Channels/101"


def test_placeholder_is_blocked_and_redacted():
    target = classify_stream_url(_PLACEHOLDER)
    assert target.blocked is True
    assert target.host_class == "placeholder"
    assert target.requirement == "edge_same_lan"
    shown = redact_stream_url(_PLACEHOLDER)
    assert "admin" not in shown
    assert "<LOCAL_IP>" in shown
    verdict = assess_hik_stream(_PLACEHOLDER, "")
    assert verdict.ok is False
    assert verdict.code == "legacy_placeholder"
    assert "192.168" not in verdict.message


def test_passwordless_rtsp_blocked_even_on_private_host():
    url = "rtsp://admin@10.1.2.3:554/Streaming/Channels/102"
    target = classify_stream_url(url)
    assert target.blocked is True
    assert target.requirement == "rtsp_credentials"
    assert not assess_hik_stream(url, "").ok


def test_private_rtsp_with_password_is_not_rewritten_or_imported():
    url = f"rtsp://admin:{_SECRET}@10.1.2.3:554/Streaming/Channels/102"
    target = classify_stream_url(url)
    assert target.blocked is False
    assert target.host_class == "private"
    assert target.requirement == "same_lan"
    assert target.has_credentials is True
    shown = redact_stream_url(url)
    assert _SECRET not in shown
    assert "10.1.2.3" in shown
    verdict = assess_hik_stream(url, "rtsp")
    assert verdict.ok is False
    assert verdict.code == "lan_unroutable"
    assert _SECRET not in verdict.message
    assert "10.1.2.3" not in verdict.message


def test_public_and_hostname_streams_can_be_imported():
    rtsp = f"rtsp://user:{_SECRET}@1.1.1.1:554/Streaming/Channels/101"
    host = f"rtsp://user:{_SECRET}@nvr.example.com:554/Streaming/Channels/202"
    hls = "https://cdn.example/live/index.m3u8?token=abc"
    assert assess_hik_stream(rtsp, "rtsp").ok is True
    assert assess_hik_stream(host, "rtsp").ok is True
    assert assess_hik_stream(hls, "hls").ok is True
    assert "token" not in redact_stream_url(hls)
    assert "abc" not in redact_text(f"failed {hls}")


def test_rtsp_lan_protocol_is_rejected():
    verdict = assess_hik_stream("", "rtsp-lan")
    assert verdict.ok is False
    assert verdict.code == "lan_unroutable"


def test_builder_refuses_placeholder_and_missing_password():
    with pytest.raises(ValueError):
        HikConnectClient.build_rtsp_url("<LOCAL_IP>", username="admin", password=_SECRET)
    with pytest.raises(ValueError):
        HikConnectClient.build_rtsp_url("10.1.2.3", username="admin", password="")
    built = HikConnectClient.build_rtsp_url(
        "1.1.1.1", username="admin", password=_SECRET, channel=3, stream="sub",
    )
    assert built.endswith("/Streaming/Channels/302")
    assert _SECRET in built


def test_legacy_placeholder_is_listed_but_not_opened_or_rewritten():
    manager = PipelineManager()
    manager.add_camera(CameraConfig(id="legacy", url=_PLACEHOLDER, name="nvr"))
    assert "legacy" not in manager._tasks
    stored = manager._cameras["legacy"].url
    assert stored == _PLACEHOLDER
    row = manager.list_cameras()[0]
    assert row["stream_status"] == "unreachable"
    assert row["running"] is False
    assert row["frames_received"] == 0
    assert "admin@" not in row["url"]
    diag = manager.diagnostics("legacy")
    assert diag is not None
    assert diag["lan_substituted"] is False
    assert "не переписывается" in diag["message"]


@pytest.mark.asyncio
async def test_demo_is_not_online_before_a_frame():
    reader = CameraReader(CameraConfig(id="demo-1", url="demo", fps_inference=20))
    assert reader.state.status == "connecting"
    assert reader.state.frames_received == 0
    agen = reader.stream()
    frame = await agen.__anext__()
    assert frame.is_demo is True
    assert reader.state.frames_received == 1
    assert reader.state.status == "demo"
    await agen.aclose()


@pytest.mark.asyncio
async def test_empty_cloud_response_does_not_invent_placeholder():
    client = HikConnectClient("user@example.com", "not-a-real-password", "ru")
    client._session_id = "session"
    client._login_valid_until = datetime.datetime.now() + datetime.timedelta(days=1)
    empty = {"meta": {"code": 200}}
    client._api_post_form = AsyncMock(return_value=empty)  # type: ignore[method-assign]
    client._api_get = AsyncMock(return_value={"meta": {"code": 200}})  # type: ignore[method-assign]
    client.get_devices = AsyncMock(return_value=[])  # type: ignore[method-assign]
    stream = await client.get_live_stream_url("DEVICE", 1)
    assert stream.url == ""
    assert stream.protocol != "rtsp-lan"
    assert "<LOCAL_IP>" not in str(stream.raw)
    await client.close()


def test_cloud_query_ticket_is_playable_and_not_a_device_password():
    ticket = "ticket-value"
    access = "access-value"
    url = f"rtmp://cdn.example/live?t={ticket}&accessToken={access}"
    target = classify_stream_url(url)
    assert target.blocked is False
    assert target.has_credentials is True
    assert target.host_class == "hostname"
    verdict = assess_hik_stream(url, "rtmp")
    assert verdict.ok is True
    assert ticket not in verdict.message
    private = f"rtsp://10.1.2.3:554/Streaming/Channels/102?t={ticket}"
    assert classify_stream_url(private).blocked is True
    assert ticket not in classify_stream_url(private).reason


def test_error_text_drops_query_tickets():
    ticket = "ticket-value"
    access = "access-value"
    raw = f"OpenCV cannot open: rtmp://cdn.example/live?t={ticket}&accessToken={access}"
    cleaned = redact_text(raw)
    assert ticket not in cleaned
    assert access not in cleaned
    assert "?" not in cleaned
    assert "cdn.example" in cleaned


def test_last_error_on_the_public_row_is_redacted():
    ticket = "ticket-value"
    manager = PipelineManager()
    url = "https://cdn.example/live.m3u8"
    manager.add_camera(
        CameraConfig(id="cloud", url=url, name="cloud", tenant_id="salon-a"),
        start=False,
    )
    manager._states["cloud"].status = "offline"
    manager._states["cloud"].last_error = f"fail rtmp://cdn.example/live?t={ticket}"
    row = manager.list_cameras()[0]
    diag = manager.diagnostics("cloud")
    assert ticket not in row["last_error"]
    assert diag is not None and ticket not in diag["message"] and ticket not in diag["last_error"]


def test_other_tenant_cannot_see_runtime_only_camera():
    assert caller_may_see_camera("salon-b", "salon-a", is_superadmin=False) is False
    assert caller_may_see_camera("salon-a", "salon-a", is_superadmin=False) is True
    assert caller_may_see_camera("salon-b", "salon-a", is_superadmin=True) is True
    assert caller_may_see_camera("salon-b", None, is_superadmin=False) is False
    assert hik_upsert_action("salon-a", "salon-b") == "forbidden"
    assert hik_upsert_action("salon-a", "salon-a") == "update"
    assert hik_upsert_action(None, "salon-a") == "insert"


def test_failed_save_does_not_replace_placeholder_runtime():
    manager = PipelineManager()
    cam_id = "hik-DEV-ch1"
    manager.add_camera(CameraConfig(
        id=cam_id, url=_PLACEHOLDER, name="old", tenant_id="salon-a",
    ))
    ticket = "ticket-value"
    new = CameraConfig(
        id=cam_id,
        url=f"https://cdn.example/live.m3u8?t={ticket}",
        name="new",
        tenant_id="salon-a",
    )

    def commit() -> None:
        if hik_upsert_action("salon-a", "salon-a") != "update":
            raise AssertionError("expected update")
        raise RuntimeError("integrity")

    started = False
    try:
        commit()
        started = True
        manager.remove_camera(cam_id)
        manager.add_camera(new, start=False)
    except RuntimeError as exc:
        assert str(exc) == "integrity"
    assert started is False
    assert manager._cameras[cam_id].url == _PLACEHOLDER
    diag = manager.diagnostics(cam_id)
    assert diag is not None
    assert ticket not in diag["url"]
    assert diag["stream_status"] == "unreachable"


def test_committed_reimport_replaces_placeholder_without_showing_ticket():
    manager = PipelineManager()
    cam_id = "hik-DEV-ch1"
    manager.add_camera(CameraConfig(
        id=cam_id, url=_PLACEHOLDER, name="old", tenant_id="salon-a",
    ))
    ticket = "ticket-value"
    new = CameraConfig(
        id=cam_id,
        url=f"https://cdn.example/live.m3u8?t={ticket}",
        name="new",
        tenant_id="salon-a",
    )
    assert hik_upsert_action("salon-a", "salon-a") == "update"
    manager.remove_camera(cam_id)
    manager.add_camera(new, start=False)
    assert manager._cameras[cam_id].url.startswith("https://")
    row = next(c for c in manager.list_cameras() if c["id"] == cam_id)
    assert row["stream_status"] == "connecting"
    assert ticket not in row["url"]
    assert "?" not in row["url"]
