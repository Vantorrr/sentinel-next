"""Single physical weight load: cancelling the await must not start a second thread."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, patch

import pytest

from sentinel.pipeline.camera import CameraConfig
from sentinel.pipeline.manager import PipelineManager


class _Physical:
    """Blocks inside a worker thread, the same boundary as DetectionService.load."""

    allocs = 0
    loads = 0
    current = 0
    max_current = 0
    fail_once = False
    entered: asyncio.Event | None = None
    loop: asyncio.AbstractEventLoop | None = None
    releases: list[threading.Event] = []
    _lock = threading.Lock()

    def __init__(self) -> None:
        type(self).allocs += 1
        self._ready = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fake-weights")

    @property
    def ready(self) -> bool:
        return self._ready

    def _physical(self) -> None:
        release = threading.Event()
        with type(self)._lock:
            type(self).loads += 1
            attempt = type(self).loads
            type(self).current += 1
            type(self).max_current = max(type(self).max_current, type(self).current)
            type(self).releases.append(release)
        loop = type(self).loop
        entered = type(self).entered
        assert loop is not None and entered is not None
        loop.call_soon_threadsafe(entered.set)
        release.wait()
        with type(self)._lock:
            type(self).current -= 1
        if type(self).fail_once and attempt == 1:
            raise RuntimeError("weights failed")

    async def load(self) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self._physical)
        self._ready = True

    async def detect(self, _image: object) -> list[str]:
        if not self._ready:
            return []
        return ["person"]

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


class _FastReid:
    loads = 0

    def __init__(self) -> None:
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    async def load(self) -> None:
        type(self).loads += 1
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


def _reset(loop: asyncio.AbstractEventLoop) -> None:
    _Physical.allocs = 0
    _Physical.loads = 0
    _Physical.current = 0
    _Physical.max_current = 0
    _Physical.fail_once = False
    _Physical.entered = asyncio.Event()
    _Physical.loop = loop
    _Physical.releases = []
    _FastReid.loads = 0
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


def _release_all() -> None:
    for event in list(_Physical.releases):
        event.set()


@pytest.fixture
async def patched():
    _reset(asyncio.get_running_loop())
    with patch("sentinel.pipeline.manager.DetectionService", _Physical), \
            patch("sentinel.pipeline.manager.FaceReIDService", _FastReid), \
            patch("sentinel.pipeline.manager.CameraProcessor", _Probe), \
            patch("sentinel.pipeline.manager.load_zones_for_camera", new=AsyncMock(return_value=[])):
        try:
            yield
        finally:
            _release_all()


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_start_a_second_physical_load(patched):
    manager = PipelineManager()
    manager.add_camera(_cam("first"))
    assert _Physical.entered is not None
    await _Physical.entered.wait()
    assert _Physical.allocs == 1
    assert _Physical.current == 1
    assert _Physical.max_current == 1

    manager.remove_camera("first")
    _Physical.entered.clear()
    manager.add_camera(_cam("second"))
    await _until(lambda: "second" in manager._tasks)
    await asyncio.sleep(0)
    assert _Physical.allocs == 1
    assert _Physical.loads == 1
    assert _Physical.current == 1
    assert _Physical.max_current == 1
    assert manager._model_flight is not None and not manager._model_flight.done()

    _release_all()
    flight = manager._model_flight
    assert flight is not None
    await flight
    await _until(lambda: any(p.result == ["person"] for p in _Probe.created))
    assert _Physical.allocs == 1
    assert _Physical.max_current == 1
    assert _Physical.current == 0
    assert manager._detection is not None and manager._detection.ready
    assert _Probe.created[-1].detection is manager._detection
    manager.remove_camera("second")


@pytest.mark.asyncio
async def test_failed_physical_load_retries_only_after_the_thread_finishes(patched):
    _Physical.fail_once = True
    manager = PipelineManager()
    manager.add_camera(_cam("bad"))
    assert _Physical.entered is not None
    await _Physical.entered.wait()
    assert len(_Physical.releases) == 1
    _Physical.releases[0].set()
    flight = manager._model_flight
    assert flight is not None
    with pytest.raises(RuntimeError, match="weights failed"):
        await flight
    await _until(lambda: manager._states["bad"].status == "offline" and _Physical.current == 0)
    assert _Physical.allocs == 1
    assert _Physical.max_current == 1

    _Physical.entered.clear()
    manager.add_camera(_cam("good"))
    await _Physical.entered.wait()
    assert _Physical.allocs == 2
    assert _Physical.current == 1
    assert _Physical.max_current == 1
    _Physical.releases[1].set()
    await _until(lambda: any(p.result == ["person"] for p in _Probe.created))
    assert _Physical.max_current == 1
    manager.remove_camera("bad")
    manager.remove_camera("good")


@pytest.mark.asyncio
async def test_shutdown_does_not_cancel_or_duplicate_the_physical_load(patched):
    manager = PipelineManager()
    manager.add_camera(_cam("only"))
    assert _Physical.entered is not None
    await _Physical.entered.wait()
    flight = manager._model_flight
    assert flight is not None and not flight.done()

    await manager.shutdown()
    assert _Physical.allocs == 1
    assert _Physical.current == 1
    assert flight is manager._model_flight
    assert not flight.done()

    _release_all()
    await flight
    assert _Physical.allocs == 1
    assert _Physical.max_current == 1
    assert manager._detection is not None and manager._detection.ready
    await manager._ensure_models()
    assert _Physical.allocs == 1
