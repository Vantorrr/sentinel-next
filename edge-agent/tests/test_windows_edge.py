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
        if len(command) >= 3 and command[1:3] == ["-m", "venv"]:
            py = Path(command[-1]) / "Scripts" / "python.exe"
            py.parent.mkdir(parents=True, exist_ok=True)
            py.write_text("", encoding="utf-8")

    base = Path(r"C:\Program Files\Python312\python.exe")
    first = apply_install(root, data, runner, base)
    assert "pip" in first
    saved = (data / "private" / "config.env").read_text(encoding="utf-8")
    assert "salon-key" in saved
    assert "SECRET" not in (root / ".env").read_text(encoding="utf-8")
    assert str(data / "models" / "yolo11n.pt") in saved
    second = apply_install(root, data, runner, base)
    if sys.platform == "win32":
        import subprocess
        assert "pip" in second
        subprocess.run(
            ["takeown", "/F", str(data / "app" / ".venv"), "/A", "/R", "/D", "Y"],
            check=True,
            capture_output=True,
            text=True,
        )
        third = apply_install(root, data, runner, base)
        assert "pip" not in third
        saved_again = (data / "private" / "config.env").read_text(encoding="utf-8")
        assert saved_again == saved
    else:
        assert "pip" not in second
    assert (data / "private" / "config.env").read_text(encoding="utf-8") == saved
    pip_calls = [item for item in calls if "pip" in item]
    assert any("https://download.pytorch.org/whl/cpu" in part for item in pip_calls for part in item)
    assert all(isinstance(item, list) for item in calls)
    assert any(str(base) in item for item in calls)
    assert not any("-e" in part for item in calls for part in item)
    assert not any("LocalAppData" in part for item in calls for part in item)
    xml = (data / "SentinelEdge.xml").read_text(encoding="utf-16")
    assert str(data / "app" / ".venv") in xml
    assert str(data / "private" / "config.env") in xml
    assert str(root) not in xml
    assert "SECRET" not in xml
    presets = [item[-1] for item in calls if item[:5] == ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]]
    assert presets[:6] == ["data", "private", "app", "models", "control", "logs"]
    script = Path(__file__).resolve().parents[1] / "packaging" / "Set-SentinelAcl.ps1"
    script_text = script.read_text(encoding="utf-8")
    private_block = script_text.split('"private" {', 1)[1].split('"app" {', 1)[0]
    control_block = script_text.split('"control" {', 1)[1].split('"logs" {', 1)[0]
    assert "S-1-5-32-545" not in private_block
    assert "S-1-5-32-545" in control_block
    from sentinel_edge.install_win import package_digest, stamp_material
    stamp = data / "install-stamp.txt"
    venv_python = data / "app" / ".venv" / "Scripts" / "python.exe"
    text = stamp_material(
        (root / "requirements-windows.txt").read_text(encoding="utf-8"),
        (root / "requirements-torch-cpu.txt").read_text(encoding="utf-8"),
        package_digest(root),
    )
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


def test_package_root_and_config_env(tmp_path: Path):
    from sentinel_edge.install_win import resolve_package_root
    root = tmp_path / "SentinelEdge"
    (root / "sentinel_edge").mkdir(parents=True)
    (root / "sentinel_edge" / "cli.py").write_text("", encoding="utf-8")
    (root / "requirements-windows.txt").write_text("x\n", encoding="utf-8")
    (root / "requirements-torch-cpu.txt").write_text("torch==2.5.1\n", encoding="utf-8")
    nested = root / "packaging"
    nested.mkdir()
    assert resolve_package_root(nested) == root.resolve()
    assert resolve_package_root(root) == root.resolve()
    data = tmp_path / "data"
    (root / "config.env").write_text(
        "SENTINEL_API_URL=https://from-config.example\nSENTINEL_API_KEY=from-file\nSENTINEL_YOLO_MODEL=yolo11n.pt\n",
        encoding="utf-8",
    )
    (root / "env.example").write_text("SENTINEL_API_URL=https://example.test\n", encoding="utf-8")
    dest = data / "private" / "config.env"
    calls: list[list[str]] = []

    def runner(command: list[str]) -> None:
        calls.append(command)
        if len(command) >= 3 and command[1:3] == ["-m", "venv"]:
            py = Path(command[-1]) / "Scripts" / "python.exe"
            py.parent.mkdir(parents=True, exist_ok=True)
            py.write_text("", encoding="utf-8")

    apply_install(root, data, runner, Path(r"C:\Program Files\Python312\python.exe"))
    saved = dest.read_text(encoding="utf-8")
    assert "from-file" in saved
    assert "yolo11n.pt" not in saved.split("SENTINEL_YOLO_MODEL=", 1)[-1].splitlines()[0] or str(data) in saved
    assert str(data / "models" / "yolo11n.pt") in saved
    assert "from-file" not in (root / "config.env").read_text(encoding="utf-8")


def test_cwd_dotenv_is_loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "SENTINEL_API_URL=https://from-dotenv.example\nSENTINEL_API_KEY=k\nSENTINEL_CAMERAS=file\n",
        encoding="utf-8",
    )
    settings = load_settings(None)
    assert settings.api_url == "https://from-dotenv.example"
    assert settings.camera_list() == ["file"]


def test_frame_interval_follows_configured_fps():
    from sentinel_edge.camera import capture_interval
    assert capture_interval(2) == 0.5
    assert capture_interval(0) == 1.0
    source = Path(__file__).resolve().parents[1].joinpath("sentinel_edge", "cli.py").read_text(encoding="utf-8")
    assert "frame_interval=capture_interval(settings.fps_inference)" in source
    assert 'data / "private" / "edge.pid"' in source


def test_bat_scripts_split_status_stop_and_python():
    packaging = Path(__file__).resolve().parents[1] / "packaging"
    install = (packaging / "Install.bat").read_text(encoding="utf-8")
    status = (packaging / "Status.bat").read_text(encoding="utf-8")
    stop = (packaging / "Stop.bat").read_text(encoding="utf-8")
    assert "InstallAllUsers=1" in install
    assert "Assert-TrustedRoot.ps1" in install
    assert 'for %%I in ("%HERE%.") do set "ROOT=%%~fI"' in install
    assert "InstallAllUsers=0" not in install
    assert "LocalAppData" not in install
    assert r"%ProgramFiles%\Python312\python.exe" in install
    assert "status.json" in status
    assert "config.env" not in status
    assert r"control\stop.request" in stop
    assert "config.env" not in stop


def test_absolute_model_path_and_flat_config_move(tmp_path: Path):
    from sentinel_edge.install_win import installed_model_setting
    model = tmp_path / "models" / "yolo11n.pt"
    assert installed_model_setting("yolo11n.pt", model) == str(model)
    custom = r"D:\weights\custom.pt"
    assert installed_model_setting(custom, model) == custom
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "env.example").write_text("SENTINEL_API_URL=https://example.test\n", encoding="utf-8")
    (root / "requirements-windows.txt").write_text("x\n", encoding="utf-8")
    (root / "requirements-torch-cpu.txt").write_text("torch==2.5.1\n", encoding="utf-8")
    data = tmp_path / "data"
    (data).mkdir()
    (data / "config.env").write_text("SENTINEL_API_KEY=flat-secret\nSENTINEL_YOLO_MODEL=yolo11n.pt\n", encoding="utf-8")

    def runner(command: list[str]) -> None:
        if len(command) >= 3 and command[1:3] == ["-m", "venv"]:
            py = Path(command[-1]) / "Scripts" / "python.exe"
            py.parent.mkdir(parents=True, exist_ok=True)
            py.write_text("", encoding="utf-8")

    apply_install(root, data, runner, Path(r"C:\Program Files\Python312\python.exe"))
    saved = (data / "private" / "config.env").read_text(encoding="utf-8")
    assert "flat-secret" in saved
    assert "flat-secret" not in (data / "config.env").read_text(encoding="utf-8")
    assert str(model) not in saved
    assert str(data / "models" / "yolo11n.pt") in saved


@pytest.mark.asyncio
async def test_read_failure_clears_opened(monkeypatch: pytest.MonkeyPatch):
    from sentinel_edge.health import CameraHealth

    class FakeCapture:
        def __init__(self, _source: object) -> None:
            self.reads = 0

        def isOpened(self) -> bool:
            return True

        def read(self):
            self.reads += 1
            if self.reads == 1:
                return True, np.zeros((2, 2, 3), dtype=np.uint8)
            return False, None

        def release(self) -> None:
            return None

    monkeypatch.setattr(cv2, "VideoCapture", FakeCapture)
    record = CameraHealth(camera_id="cam", label="camera")

    def sync(stream: CameraStream, target=record) -> None:
        target.opened = stream.opened
        target.frames = stream._frames
        target.last_error = stream.last_error

    stream = CameraStream("rtsp://camera.example/stream", reconnect_delay=30, on_change=sync)
    agen = stream.frames()
    frame = await agen.__anext__()
    assert frame.shape == (2, 2, 3)
    assert record.opened is True
    assert record.frames == 1
    assert record.last_error == ""
    pending = asyncio.create_task(agen.__anext__())
    for _ in range(50):
        if record.last_error == "read failed":
            break
        await asyncio.sleep(0.01)
    assert record.opened is False
    assert record.last_error == "read failed"
    assert record.frames == 1
    pending.cancel()
    try:
        await pending
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_overlapping_flushes_do_not_drop_unsent_events(tmp_path: Path):
    from sentinel_edge.config import EdgeSettings

    class Response:
        status_code = 200

    class PausingClient:
        def __init__(self) -> None:
            self.calls: list[int] = []
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def post(self, path: str, json: dict):
            self.calls.append(json["events"][0]["n"])
            if len(self.calls) == 1:
                self.started.set()
                await self.release.wait()
            return Response()

    settings = EdgeSettings(
        api_url="http://sentinel.test",
        api_key="k",
        agent_id="a",
        cameras="file",
        event_batch_size=1,
    )
    client = PausingClient()
    sender = EventSender(settings, tmp_path / "queue.json", RuntimeHealth(), client=client)
    sender.push({"type": "occupancy.update", "camera_id": "c", "n": 1, "payload": {}})
    sender.push({"type": "occupancy.update", "camera_id": "c", "n": 2, "payload": {}})
    first = asyncio.create_task(sender._flush())
    await client.started.wait()
    second = asyncio.create_task(sender._flush())
    await asyncio.sleep(0)
    assert client.calls == [1]
    client.release.set()
    await asyncio.gather(first, second)
    assert client.calls == [1, 2]
    assert sender._queue.events == []


def _install_root(tmp_path: Path):
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "env.example").write_text("SENTINEL_API_URL=https://example.test\n", encoding="utf-8")
    (root / "requirements-windows.txt").write_text("x\n", encoding="utf-8")
    (root / "requirements-torch-cpu.txt").write_text("torch==2.5.1\n", encoding="utf-8")
    (root / "sentinel_edge").mkdir()
    (root / "sentinel_edge" / "cli.py").write_text("x = 1\n", encoding="utf-8")
    calls: list[list[str]] = []

    def runner(command: list[str]) -> None:
        calls.append(command)
        if len(command) >= 3 and command[1:3] == ["-m", "venv"]:
            py = Path(command[-1]) / "Scripts" / "python.exe"
            py.parent.mkdir(parents=True, exist_ok=True)
            py.write_text("", encoding="utf-8")

    return root, tmp_path / "data", calls, runner


def test_new_venv_and_source_change_reinstall(tmp_path: Path):
    import shutil
    root, data, calls, runner = _install_root(tmp_path)
    base = Path(r"C:\Program Files\Python312\python.exe")
    assert "pip" in apply_install(root, data, runner, base)
    shutil.rmtree(data / "app" / ".venv")
    assert "pip" in apply_install(root, data, runner, base)
    (root / "sentinel_edge" / "cli.py").write_text("x = 2\n", encoding="utf-8")
    assert "pip" in apply_install(root, data, runner, base)
    assert calls


def test_symlink_data_dir_is_refused(tmp_path: Path):
    root, _data, calls, runner = _install_root(tmp_path)
    target = tmp_path / "elsewhere"
    target.mkdir()
    link = tmp_path / "linked"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("creating a directory symlink is not allowed")
    with pytest.raises(RuntimeError, match="symlink"):
        apply_install(root, link, runner, Path(r"C:\Program Files\Python312\python.exe"))
    assert calls == []


def test_crash_log_does_not_dump_locals(tmp_path: Path):
    from loguru import logger
    from sentinel_edge.cli import _setup_log
    secret = "salon-api-key-value"
    _setup_log(tmp_path / "edge.log", "INFO")

    def boom() -> None:
        api_key = secret
        if not api_key:
            return
        raise RuntimeError("failed")

    try:
        boom()
    except RuntimeError:
        logger.exception("Agent crashed: {}", "RuntimeError")
    assert secret not in (tmp_path / "edge.log").read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform != "win32", reason="powershell ACL")
def test_trusted_root_rejects_users_write(tmp_path: Path):
    import subprocess
    script = Path(__file__).resolve().parents[1] / "packaging" / "Assert-TrustedRoot.ps1"
    opened = tmp_path / "open"
    opened.mkdir()
    subprocess.run(["icacls", str(opened), "/inheritance:d"], check=True, capture_output=True, text=True)
    subprocess.run(
        ["icacls", str(opened), "/grant:r", "*S-1-5-32-545:(OI)(CI)M"],
        check=True,
        capture_output=True,
        text=True,
    )
    failed = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Root", str(opened)],
        capture_output=True,
        text=True,
    )
    listed = subprocess.run(["icacls", str(opened)], capture_output=True, text=True)
    assert failed.returncode == 3, listed.stdout + failed.stdout + failed.stderr
    subprocess.run(
        ["icacls", str(opened), "/remove:g", "*S-1-5-32-545"],
        check=True,
        capture_output=True,
        text=True,
    )
    allowed = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Root", str(opened)],
        capture_output=True,
        text=True,
    )
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="icacls exists on the Windows runner")
def test_real_icacls_removes_users_from_private(tmp_path: Path):
    import subprocess
    from sentinel_edge.install_win import acl_commands

    data = tmp_path / "SentinelEdge"
    for name in ("private", "app", "models", "control", "logs"):
        (data / name).mkdir(parents=True)
    secret = data / "private" / "config.env"
    secret.write_text("SENTINEL_API_KEY=secret\n", encoding="utf-8")
    subprocess.run(
        ["icacls", str(data / "private"), "/grant", "*S-1-5-32-546:(OI)(CI)M"],
        check=True,
        capture_output=True,
        text=True,
    )
    for _ in range(2):
        for command in acl_commands(data):
            subprocess.run(command, check=True, capture_output=True, text=True)
    def aces(target: Path) -> str:
        listing = subprocess.run(["icacls", str(target)], check=True, capture_output=True, text=True)
        return listing.stdout.replace(str(target), "")

    assert "Users" not in aces(secret)
    assert "Guests" not in aces(data / "private")
    status = data / "status.json"
    status.write_text("{}\n", encoding="utf-8")
    assert "Users" in aces(status)
    stop = data / "control" / "stop.request"
    stop.write_text("stop\n", encoding="utf-8")
    assert "Users" in aces(stop)
    assert "Users" not in aces(data / "app")
    for line in aces(data).splitlines():
        if "Users" in line:
            assert "(RX)" in line
            assert "(M)" not in line
            assert "(F)" not in line
