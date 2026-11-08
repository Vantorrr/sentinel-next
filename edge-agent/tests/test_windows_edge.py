"""Edge behavior that must hold before a salon PC is involved.

These tests run on the current interpreter. They do not install Windows,
reboot, or open a real camera.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import cv2
import httpx
import numpy as np
import pytest

from sentinel_edge.camera import CameraStream
from sentinel_edge.config import load_settings
from sentinel_edge.envfile import EnvError, parse_env
from sentinel_edge.health import RuntimeHealth
from sentinel_edge.install_win import (
    apply_install,
    install_actions,
    migrate_config,
    pip_commands,
    pip_needed,
    render_task_xml,
    schtasks_create_argv,
    task_command,
)
from sentinel_edge.pidlock import acquire_pid_lock
from sentinel_edge.queuefile import DurableQueue
from sentinel_edge.redact import camera_label, redact_text
from sentinel_edge.sender import EventSender
from sentinel_edge.signals import install_stop_handlers


class _BoomLoop:
    def add_signal_handler(self, *_args, **_kwargs):
        raise NotImplementedError("unix only")


class _Signal:
    SIGINT = 2
    SIGTERM = 15
    SIGBREAK = 21
    calls: list[int] = []

    @classmethod
    def signal(cls, sig, _handler):
        cls.calls.append(sig)


def test_windows_start_does_not_call_add_signal_handler():
    _Signal.calls = []
    mode = install_stop_handlers(
        lambda: None,
        platform_name="win32",
        loop=_BoomLoop(),
        signal_module=_Signal,
    )
    assert mode == "win32-console"
    assert _Signal.calls == [2, 21]


def test_paths_with_spaces_and_cyrillic(tmp_path: Path):
    folder = tmp_path / "Вай Тай салон"
    folder.mkdir()
    config = folder / "config.env"
    secret = "not-a-real-token"
    config.write_text(
        "\n".join([
            "SENTINEL_API_URL=https://example.test",
            f"SENTINEL_API_KEY={secret}",
            "SENTINEL_CAMERAS=rtsp://USER:PASSWORD@192.168.0.10:554/Streaming/Channels/102",
            f"SENTINEL_DATA_DIR={folder}",
        ]),
        encoding="utf-8",
    )
    settings = load_settings(config)
    assert settings.api_key == secret
    assert settings.camera_list()[0].endswith("/102")
    xml = render_task_xml(folder / "python.exe", config, folder)
    assert "Вай Тай салон" in xml
    assert secret not in xml
    assert "<Hidden>false</Hidden>" in xml
    command, arguments = task_command(folder / "python.exe", config)
    assert " " in str(config)
    assert secret not in arguments
    argv = schtasks_create_argv(folder / "SentinelEdge.xml")
    assert str(folder / "SentinelEdge.xml") in argv


def test_config_rejects_commands_and_redacts_urls():
    with pytest.raises(EnvError):
        parse_env("SENTINEL_API_URL=$(calc)")
    with pytest.raises(EnvError):
        parse_env("SENTINEL_CAMERAS=`whoami`")
    secret = "camera-password"
    token = "api-token-value"
    raw = f"rtsp://admin:{secret}@192.168.0.10:554/Streaming/Channels/102?t={token}"
    cleaned = redact_text(f"open {raw} SENTINEL_API_KEY={token}")
    assert secret not in cleaned
    assert token not in cleaned
    assert "192.168.0.10" in camera_label(raw)
    assert secret not in camera_label(raw)


def test_install_is_idempotent_and_keeps_config(tmp_path: Path):
    root = tmp_path / "pkg"
    data = tmp_path / "ProgramData" / "SentinelEdge"
    root.mkdir()
    (root / "packaging").mkdir()
    (root / "packaging" / "env.example").write_text(
        "SENTINEL_API_URL=https://example.test\nSENTINEL_API_KEY=\nSENTINEL_CAMERAS=\n",
        encoding="utf-8",
    )
    (root / "requirements-windows.txt").write_text("httpx==0.28.1\n", encoding="utf-8")
    (root / "requirements-torch-cpu.txt").write_text("torch==2.5.1\n", encoding="utf-8")
    legacy = root / ".env"
    legacy.write_text(
        "SENTINEL_API_URL=https://salon.example\nSENTINEL_API_KEY=salon-key\n"
        "SENTINEL_CAMERAS=rtsp://USER:SECRET@192.168.0.10:554/Streaming/Channels/102\n",
        encoding="utf-8",
    )
    venv_python = root / ".venv" / "Scripts" / "python.exe"
    calls: list[list[str]] = []

    def runner(command: list[str]) -> None:
        calls.append(command)
        if command[1:3] == ["-m", "venv"]:
            venv_python.parent.mkdir(parents=True, exist_ok=True)
            venv_python.write_text("", encoding="utf-8")

    first = apply_install(root, data, runner)
    assert "pip" in first
    saved = (data / "config.env").read_text(encoding="utf-8")
    assert "salon-key" in saved
    assert "SECRET" in saved
    second = apply_install(root, data, runner)
    assert "pip" not in second
    assert (data / "config.env").read_text(encoding="utf-8") == saved
    pip_calls = [item for item in calls if "pip" in item]
    assert any("https://download.pytorch.org/whl/cpu" in part for item in pip_calls for part in item)
    assert all(isinstance(item, list) for item in calls)
    stamp = data / "install-stamp.txt"
    text = (root / "requirements-windows.txt").read_text() + (root / "requirements-torch-cpu.txt").read_text()
    assert pip_needed(stamp, text, venv_python) is False
    model = data / "models" / "yolo11n.pt"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"model")
    assert install_actions(
        venv_python=venv_python,
        stamp_path=stamp,
        requirements_text=text,
        model_path=data / "models" / "yolo11n.pt",
        task_registered=True,
    ) == []


def _write_clip(path: Path) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 5, (320, 240))
    assert writer.isOpened()
    for i in range(4):
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.rectangle(frame, (10 + i * 15, 30), (80 + i * 15, 120), (255, 255, 255), -1)
        writer.write(frame)
    writer.release()


@pytest.mark.asyncio
async def test_offline_file_then_decoded_frame(tmp_path: Path):
    clip = tmp_path / "клип салон.avi"
    stream = CameraStream(str(clip), camera_id="cam", reconnect_delay=0.01)
    agen = stream.frames()
    task = asyncio.create_task(agen.__anext__())
    await asyncio.sleep(0.05)
    assert stream._frames == 0
    assert stream.opened is False
    _write_clip(clip)
    frame = await asyncio.wait_for(task, timeout=2)
    assert frame.shape == (240, 320, 3)
    assert stream._frames == 1
    assert stream.last_frame_wall is not None
    await agen.aclose()


@pytest.mark.asyncio
async def test_api_503_and_timeout_then_delivery(tmp_path: Path):
    from sentinel_edge.config import EdgeSettings
    health = RuntimeHealth()
    queue = tmp_path / "queue.json"
    settings = EdgeSettings(api_url="http://127.0.0.1:9", api_key="k", agent_id="a", cameras="file")
    state = {"fail": True, "events": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["fail"]:
            return httpx.Response(503)
        state["events"] += 1
        return httpx.Response(200, json={"accepted": 1})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(base_url="http://sentinel.test", transport=transport)
    sender = EventSender(settings, queue, health, fps_provider=lambda: 4.5, client=client)
    sender.push({"type": "client.entered", "camera_id": "edge-a-cam-0", "track_id": "1", "confidence": 0.5, "payload": {}})
    await sender._flush()
    assert health.last_event_status == 503
    assert len(sender._queue.events) == 1
    state["fail"] = False
    await sender._flush()
    assert state["events"] == 1
    assert sender._queue.events == []
    await sender.send_heartbeat()
    assert health.last_heartbeat_status == 200
    assert health.fps == 4.5
    body = sender._queue.events
    assert body == []
    await client.aclose()


def test_queue_survives_restart_and_is_bounded(tmp_path: Path):
    path = tmp_path / "queue.json"
    first = DurableQueue(path, maxlen=3)
    for i in range(5):
        first.push({"type": "occupancy.update", "camera_id": "c", "n": i})
    assert len(first.events) == 3
    assert first.dropped == 2
    assert first.events[0]["n"] == 2
    second = DurableQueue(path, maxlen=3)
    assert [item["n"] for item in second.events] == [2, 3, 4]
    second.ack(1)
    third = DurableQueue(path, maxlen=3)
    assert [item["n"] for item in third.events] == [3, 4]


def test_lock_and_uninstall_keep_config(tmp_path: Path):
    import subprocess
    lock = tmp_path / "edge.pid"
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    lock.write_text(str(other.pid), encoding="utf-8")
    try:
        assert acquire_pid_lock(lock) is False
    finally:
        other.kill()
        other.wait(timeout=5)
    config = tmp_path / "config.env"
    config.write_text("SENTINEL_API_KEY=keep-me\n", encoding="utf-8")
    assert migrate_config(None, config, "SENTINEL_API_KEY=\n") == "kept"
    assert "keep-me" in config.read_text(encoding="utf-8")


def test_packaging_scripts_do_not_reinstall_on_service_start():
    root = Path(__file__).resolve().parents[1] / "packaging"
    install = (root / "Install.bat").read_text(encoding="utf-8")
    assert "install_win" in install
    assert "torch" not in install.lower()
    service = render_task_xml(Path(r"C:\SentinelEdge\.venv\Scripts\python.exe"), Path(r"C:\ProgramData\SentinelEdge\config.env"), Path(r"C:\SentinelEdge"))
    assert "pip" not in service
    assert "Hidden>false" in service
    commands = pip_commands(Path("py.exe"), Path("torch.txt"), Path("req.txt"))
    assert commands[1][-1] == "https://download.pytorch.org/whl/cpu"
