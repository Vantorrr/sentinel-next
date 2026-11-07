"""Cancelled or failed warmup must not stick as a not-ready model singleton."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from sentinel.pipeline.camera import CameraConfig
from sentinel.pipeline.manager import PipelineManager


class _Det:
    loads = 0
    gate: asyncio.Event | None = None
    entered: asyncio.Event | None = None

    def __init__(self) -> None:
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    async def load(self) -> None:
        type(self).loads += 1
        if type(self).loads == 1 and type(self).gate is not None:
            assert type(self).entered is not None
            type(self).entered.set()
            await type(self).gate.wait()
        self._ready = True

    async def detect(self, _image: object) -> list[str]:
        if not self._ready:
            return []
        return ["person"]


class _Reid:
    loads = 0
    fail_once = False

    def __init__(self) -> None:
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    async def load(self) -> None:
        type(self).loads += 1
        if type(self).fail_once and type(self).loads == 1:
            raise RuntimeError("reid weights missing")
        self._ready = True


class _Probe:
    created: list["_Probe"] = []

    def __init__(self, reader, detection_svc, **_kwargs: object) -> None:
        self.state = reader.state
        self.detection = detection_svc
        self.result: list[str] = []
        _Probe.created.append(self)

    async def run(self) -> None:
        self.result = await self.detection.detect(None)
        self.state.frames_received += 1
        self.state.status = "online"
        await asyncio.Event().wait()


def _reset() -> None:
    _Det.loads = 0
    _Det.gate = None
    _Det.entered = None
    _Reid.loads = 0
    _Reid.fail_once = False
    _Probe.created = []


def _cam(name: str) -> CameraConfig:
    return CameraConfig(
        id=name,
        url=f"https://cdn.example/{name}.m3u8",
        name=name,
        tenant_id="salon-a",
    )


async def _until(pred, steps: int = 50) -> None:
    for _ in range(steps):
        if pred():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition was not met")


@pytest.fixture
def patched():
    _reset()
    with patch("sentinel.pipeline.manager.DetectionService", _Det), \
            patch("sentinel.pipeline.manager.FaceReIDService", _Reid), \
            patch("sentinel.pipeline.manager.CameraProcessor", _Probe), \
            patch("sentinel.pipeline.manager.load_zones_for_camera", new=AsyncMock(return_value=[])):
        yield


@pytest.mark.asyncio
async def test_cancel_during_warmup_then_next_camera_detects(patched):
    gate = asyncio.Event()
    entered = asyncio.Event()
    _Det.gate = gate
    _Det.entered = entered
    manager = PipelineManager()

    manager.add_camera(_cam("first"))
    await entered.wait()
    assert manager._detection is None or not manager._detection.ready

    assert manager.remove_camera("first") is True
    await _until(lambda: "first" not in manager._tasks)
    assert _Det.loads == 1
    flight = manager._model_flight
    assert flight is not None and not flight.done()

    manager.add_camera(_cam("second"))
    gate.set()
    await _until(lambda: any(p.state.frames_received == 1 for p in _Probe.created))
    assert _Det.loads == 1

    probe = _Probe.created[-1]
    assert probe.result == ["person"]
    assert manager._detection is not None and manager._detection.ready
    assert manager._reid is not None and manager._reid.ready
    assert probe.detection is manager._detection
    manager.remove_camera("second")


@pytest.mark.asyncio
async def test_waiting_camera_finishes_load_if_holder_is_cancelled(patched):
    gate = asyncio.Event()
    entered = asyncio.Event()
    _Det.gate = gate
    _Det.entered = entered
    manager = PipelineManager()

    manager.add_camera(_cam("holder"))
    await entered.wait()
    manager.add_camera(_cam("waiter"))
    await _until(lambda: manager._model_flight is not None and not manager._model_flight.done())

    manager.remove_camera("holder")
    assert _Det.loads == 1
    gate.set()
    await _until(lambda: any(p.result == ["person"] for p in _Probe.created))

    assert _Det.loads == 1
    assert manager._detection is not None and manager._detection.ready
    assert _Probe.created[-1].result == ["person"]
    assert "holder" not in manager._cameras
    manager.remove_camera("waiter")


@pytest.mark.asyncio
async def test_two_cameras_share_one_ready_model(patched):
    gate = asyncio.Event()
    entered = asyncio.Event()
    _Det.gate = gate
    _Det.entered = entered
    manager = PipelineManager()

    manager.add_camera(_cam("a"))
    await entered.wait()
    manager.add_camera(_cam("b"))
    gate.set()
    await _until(lambda: len(_Probe.created) == 2 and all(p.result == ["person"] for p in _Probe.created))

    assert _Det.loads == 1
    assert _Probe.created[0].detection is _Probe.created[1].detection
    assert _Probe.created[0].result == ["person"]
    assert _Probe.created[1].result == ["person"]
    manager.remove_camera("a")
    manager.remove_camera("b")


@pytest.mark.asyncio
async def test_failed_load_is_retried_for_the_next_camera(patched):
    _Reid.fail_once = True
    manager = PipelineManager()

    manager.add_camera(_cam("bad"))
    await _until(lambda: manager._states["bad"].status == "offline")
    assert manager._reid is None
    assert manager._states["bad"].last_error

    manager.add_camera(_cam("good"))
    await _until(lambda: any(p.result == ["person"] for p in _Probe.created))
    assert manager._detection is not None and manager._detection.ready
    assert manager._reid is not None and manager._reid.ready
    assert _Reid.loads == 2
    manager.remove_camera("bad")
    manager.remove_camera("good")
