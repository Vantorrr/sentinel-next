"""
Visitor heatmap accumulator.

Maintains a per-camera Gaussian-weighted presence grid.
The frontend renders this as a D3/Three.js overlay.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

import numpy as np


GRID_W = 64  # resolution of the heatmap grid
GRID_H = 36


class HeatmapService:
    def __init__(self) -> None:
        self._grids: dict[str, np.ndarray] = defaultdict(
            lambda: np.zeros((GRID_H, GRID_W), dtype=np.float32)
        )
        self._decay = 0.995   # per-frame exponential decay
        self._last_update: dict[str, float] = {}

    async def update(self, camera_id: str, points: list[tuple[float, float]]) -> None:
        """
        Points are (cx, cy) in pixel coordinates relative to the camera frame.
        We normalise to [0,1] then map to grid indices.
        """
        grid = self._grids[camera_id]
        grid *= self._decay

        for cx, cy in points:
            # Assume 1920x1080 source; normalise
            gx = int(min(cx / 1920, 0.999) * GRID_W)
            gy = int(min(cy / 1080, 0.999) * GRID_H)
            # Gaussian splat 3x3
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    nx, ny = gx + dx, gy + dy
                    if 0 <= nx < GRID_W and 0 <= ny < GRID_H:
                        weight = 1.0 if dx == 0 and dy == 0 else 0.5
                        grid[ny, nx] = min(grid[ny, nx] + weight, 255)

        self._last_update[camera_id] = time.time()

    def get_snapshot(self, camera_id: str) -> dict[str, Any]:
        grid = self._grids.get(camera_id, np.zeros((GRID_H, GRID_W)))
        # Normalize to [0,255] uint8 for transfer efficiency
        mx = grid.max()
        if mx > 0:
            normalized = (grid / mx * 255).astype(np.uint8)
        else:
            normalized = grid.astype(np.uint8)
        return {
            "camera_id": camera_id,
            "width": GRID_W,
            "height": GRID_H,
            "data": normalized.flatten().tolist(),
            "max_value": float(mx),
            "timestamp": self._last_update.get(camera_id, 0),
        }

    def reset(self, camera_id: str) -> None:
        self._grids[camera_id] = np.zeros((GRID_H, GRID_W), dtype=np.float32)
