"""Sentinel Edge commands. `run` does not install packages or print camera URLs."""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys
import time
from pathlib import Path

from loguru import logger

from sentinel_edge.config import load_settings
from sentinel_edge.health import RuntimeHealth, write_status
from sentinel_edge.pidlock import acquire_pid_lock, release_pid_lock
from sentinel_edge.redact import camera_label, redact_text
from sentinel_edge.signals import install_stop_handlers


def _data_dir(settings_data: str, config_path: Path | None) -> Path:
    if settings_data:
        return Path(settings_data)
    if config_path is not None:
        return config_path.parent
    return Path.cwd()


def _setup_log(path: Path, level: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    logger.remove()

    def _patch(record: dict) -> None:
        record["message"] = redact_text(str(record["message"]))

    logger.configure(patcher=_patch)
    logger.add(sys.stderr, level=level, format="{time:HH:mm:ss} | {level} | {message}")
    logger.add(
        path,
        level=level,
        rotation="1 MB",
        retention=5,
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    )


async def _run_async(config_path: Path | None, stop_flag: dict[str, bool]) -> None:
    from sentinel_edge.camera import CameraStream, capture_interval
    from sentinel_edge.detector import LocalDetector
    from sentinel_edge.sender import EventSender

    settings = load_settings(config_path)
    problems = settings.errors()
    data = _data_dir(settings.data_dir, config_path)
    health = RuntimeHealth()
    status_path = data / "status.json"
    if problems:
        health.state = "config_error"
        write_status(status_path, health)
        for item in problems:
            logger.error("{}", item)
        return

    lock_path = data / "edge.pid"
    if not acquire_pid_lock(lock_path):
        health.state = "already_running"
        write_status(status_path, health)
        logger.error("Another edge process is already running")
        return

    detector = LocalDetector(settings)
    detector.load()
    (data / "private").mkdir(parents=True, exist_ok=True)
    sender = EventSender(
        settings,
        data / "private" / "queue.json",
        health,
        fps_provider=lambda: detector.fps,
    )
    await sender.start()
    sources = settings.camera_list()
    logger.info("Cameras configured: {}", len(sources))
    for idx, source in enumerate(sources):
        cam_id = f"edge-{settings.agent_id}-cam-{idx}"
        health.cameras[cam_id] = health.cameras.get(cam_id) or _camera_health(cam_id, source)

    stop = asyncio.Event()

    def request_stop() -> None:
        stop_flag["stop"] = True
        stop.set()

    install_stop_handlers(
        request_stop,
        platform_name=sys.platform,
        loop=asyncio.get_running_loop(),
        signal_module=signal,
    )
    stop_path = data / "control" / "stop.request"
    stop_path.parent.mkdir(parents=True, exist_ok=True)
    if stop_path.exists():
        stop_path.unlink()

    async def watch_stop() -> None:
        while not stop.is_set():
            if stop_path.exists():
                request_stop()
                return
            write_status(status_path, health)
            await asyncio.sleep(2)

    async def process_camera(source: str, idx: int) -> None:
        cam_id = f"edge-{settings.agent_id}-cam-{idx}"
        record = health.cameras[cam_id]

        def _sync(stream: CameraStream, target=record) -> None:
            target.opened = stream.opened
            target.frames = stream._frames
            target.last_open_wall = stream.last_open_wall
            target.last_frame_wall = stream.last_frame_wall
            target.last_error = stream.last_error

        stream = CameraStream(
            source,
            camera_id=cam_id,
            frame_interval=capture_interval(settings.fps_inference),
            on_change=_sync,
        )
        try:
            async for frame in stream.frames():
                record.opened = stream.opened
                record.frames = stream._frames
                record.last_open_wall = stream.last_open_wall
                record.last_frame_wall = stream.last_frame_wall
                record.last_error = stream.last_error
                if stop.is_set():
                    break
                for event in detector.process_frame(frame, cam_id):
                    sender.push(event)
        finally:
            stream.release()

    health.state = "running"
    tasks = [asyncio.create_task(process_camera(src, i)) for i, src in enumerate(sources)]
    tasks.append(asyncio.create_task(watch_stop()))
    await stop.wait()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await sender.stop()
    health.state = "stopped"
    write_status(status_path, health)
    release_pid_lock(lock_path)
    logger.info("Agent stopped")


def _camera_health(camera_id: str, source: str):
    from sentinel_edge.health import CameraHealth
    return CameraHealth(camera_id=camera_id, label=camera_label(source))


def run(config_path: Path | None) -> int:
    settings = load_settings(config_path)
    data = _data_dir(settings.data_dir, config_path)
    _setup_log(data / "logs" / "edge.log", settings.log_level)
    stop_flag = {"stop": False}
    try:
        asyncio.run(_run_async(config_path, stop_flag))
    except Exception as exc:
        logger.exception("Agent crashed: {}", type(exc).__name__)
        return 1
    return 0


def request_stop(config_path: Path | None) -> int:
    settings = load_settings(config_path)
    data = _data_dir(settings.data_dir, config_path)
    data.mkdir(parents=True, exist_ok=True)
    control = data / "control"
    control.mkdir(parents=True, exist_ok=True)
    (control / "stop.request").write_text("stop\n", encoding="utf-8")
    return 0


def status(config_path: Path | None) -> int:
    settings = load_settings(config_path)
    data = _data_dir(settings.data_dir, config_path)
    path = data / "status.json"
    if not path.exists():
        print("no status yet")
        return 1
    print(redact_text(path.read_text(encoding="utf-8")))
    return 0


def diagnose(config_path: Path | None) -> int:
    settings = load_settings(config_path)
    data = _data_dir(settings.data_dir, config_path)
    status_path = data / "status.json"
    body = status_path.read_text(encoding="utf-8") if status_path.exists() else "{}"
    log_path = data / "logs" / "edge.log"
    tail = ""
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]
        tail = "\n".join(lines)
    report = {
        "status": json.loads(redact_text(body) or "{}") if body.strip().startswith("{") else {},
        "log_tail": redact_text(tail),
        "config_problems": settings.errors(),
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    out = data / "diagnose.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sentinel-edge")
    parser.add_argument("command", choices=["run", "start", "stop", "status", "diagnose", "version"])
    parser.add_argument("--config", default="")
    args = parser.parse_args(argv)
    config = Path(args.config) if args.config else None
    if args.command == "version":
        print("0.2.0")
        return 0
    if args.command in {"run", "start"}:
        return run(config)
    if args.command == "stop":
        return request_stop(config)
    if args.command == "status":
        return status(config)
    if args.command == "diagnose":
        return diagnose(config)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
