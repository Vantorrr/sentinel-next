"""In-flight camera start must die on remove/reimport and must not feed the new state."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from sentinel.pipeline.camera import CameraConfig
from sentinel.pipeline.manager import PipelineManager

CAM = "hik-DEV-ch1"


class _HoldProcessor:
    """Records which StreamState received frames. Does not open a URL."""

    seen: list[object] = []

    def __init__(self, reader, **_kwargs: object) -> None:
        self.state = reader.state
        _HoldProcessor.seen.append(self.state)

    async def run(self) -> None:
        self.state.frames_received += 1
        self.state.status = "online"
        await asyncio.Event().wait()


async def _yield_until(pred, steps: int = 50) -> None:
    for _ in range(steps):
        if pred():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition was not met without waiting on a clock")


@pytest.fixture
def manager() -> PipelineManager:
    _HoldProcessor.seen = []
    pipe = PipelineManager()
    gate = asyncio.Event()
    started = asyncio.Event()
    calls = {"n": 0}

    async def models() -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            started.set()
            await gate.wait()

    pipe._ensure_models = models  # type: ignore[method-assign]
    pipe._gate = gate  # type: ignore[attr-defined]
    pipe._started = started  # type: ignore[attr-defined]
    return pipe


def _cam(url: str, name: str) -> CameraConfig:
    return CameraConfig(id=CAM, url=url, name=name, tenant_id="salon-a")


@pytest.mark.asyncio
async def test_reimport_during_model_load_does_not_orphan_frames(manager: PipelineManager):
    with patch("sentinel.pipeline.manager.load_zones_for_camera", new=AsyncMock(return_value=[])), \
            patch("sentinel.pipeline.manager.CameraProcessor", _HoldProcessor):
        manager.add_camera(_cam("https://cdn.example/old.m3u8", "old"))
        await manager._started.wait()  # type: ignore[attr-defined]
        old_state = manager._states[CAM]
        old_task = manager._tasks[CAM]
        assert old_state.status == "connecting"
        assert not old_task.done()

        manager.remove_camera(CAM)
        manager.add_camera(_cam("https://cdn.example/new.m3u8?t=ticket-value", "new"))
        new_state = manager._states[CAM]

        manager._gate.set()  # type: ignore[attr-defined]
        await _yield_until(lambda: new_state.frames_received == 1 and len(_HoldProcessor.seen) == 1)

        assert old_state is not new_state
        assert old_state.frames_received == 0
        assert old_state.status == "connecting"
        assert new_state.status == "online"
        assert manager._tasks[CAM] is not old_task
        assert old_task.cancelled() or old_task.done()
        row = next(item for item in manager.list_cameras() if item["id"] == CAM)
        assert row["frames_received"] == 1
        assert "ticket-value" not in row["url"]
        assert _HoldProcessor.seen == [new_state]

        manager.remove_camera(CAM)
        await _yield_until(lambda: CAM not in manager._tasks or manager._tasks[CAM].done())


@pytest.mark.asyncio
async def test_remove_during_model_load_cancels_starter(manager: PipelineManager):
    with patch("sentinel.pipeline.manager.load_zones_for_camera", new=AsyncMock(return_value=[])), \
            patch("sentinel.pipeline.manager.CameraProcessor", _HoldProcessor):
        manager.add_camera(_cam("https://cdn.example/old.m3u8", "old"))
        await manager._started.wait()  # type: ignore[attr-defined]
        old_state = manager._states[CAM]
        starter = manager._tasks[CAM]

        assert manager.remove_camera(CAM) is True
        manager._gate.set()  # type: ignore[attr-defined]
        await _yield_until(lambda: starter.done())

        assert starter.cancelled()
        assert CAM not in manager._cameras
        assert CAM not in manager._tasks
        assert old_state.frames_received == 0
        assert _HoldProcessor.seen == []


@pytest.mark.asyncio
async def test_shutdown_cancels_inflight_start(manager: PipelineManager):
    with patch("sentinel.pipeline.manager.CameraProcessor", _HoldProcessor):
        manager.add_camera(_cam("https://cdn.example/old.m3u8", "old"))
        await manager._started.wait()  # type: ignore[attr-defined]
        old_state = manager._states[CAM]
        await manager.shutdown()
        manager._gate.set()  # type: ignore[attr-defined]
        await _yield_until(lambda: not manager._tasks)

        assert old_state.frames_received == 0
        assert _HoldProcessor.seen == []
