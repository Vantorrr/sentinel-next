"""
Zone Tracker — spatial intelligence for camera zones.

Responsibilities:
  - Point-in-polygon check for each tracked person
  - Track zone enter/exit events
  - Detect staff absence from required zones
  - Detect unattended clients (proximity-based)

Integrated into CameraProcessor after ByteTrack tracking step.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from sentinel.core.events import EventType, SentinelEvent


PROXIMITY_THRESHOLD_PX = 150
ALERT_COOLDOWN_SECONDS = 300  # re-alert only after 5 min


@dataclass
class ZoneConfig:
    id: str
    name: str
    zone_type: str
    polygon: list[tuple[int, int]]
    staff_required: bool = False
    max_absence_seconds: int = 300
    max_wait_seconds: int = 120


@dataclass
class ZoneState:
    """Mutable per-zone runtime state."""
    staff_tracks: set[str] = field(default_factory=set)
    client_tracks: set[str] = field(default_factory=set)
    last_staff_seen_ms: float = 0.0
    last_absence_alert_ms: float = 0.0
    alerted_client_tracks: set[str] = field(default_factory=set)


def _point_in_polygon(x: float, y: float, polygon: list[tuple[int, int]]) -> bool:
    """Ray-casting algorithm for point-in-polygon test."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _distance(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)


class ZoneTracker:
    """Per-camera zone tracker. Created by PipelineManager for each camera."""

    def __init__(
        self,
        camera_id: str,
        location_id: str,
        tenant_id: str,
        zones: list[ZoneConfig],
    ) -> None:
        self.camera_id = camera_id
        self.location_id = location_id
        self.tenant_id = tenant_id
        self._zones = {z.id: z for z in zones}
        self._zone_states: dict[str, ZoneState] = {z.id: ZoneState() for z in zones}

        # track_id -> {zone_id: entered_at_ms}
        self._track_zones: dict[str, dict[str, float]] = {}
        # track_id -> first_seen_ms (for unattended timing)
        self._track_first_seen: dict[str, float] = {}

        if zones:
            logger.info(
                "🗺  ZoneTracker[{}] initialized with {} zones: {}",
                camera_id,
                len(zones),
                ", ".join(z.name for z in zones),
            )

    @property
    def active(self) -> bool:
        return len(self._zones) > 0

    def reload_zones(self, zones: list[ZoneConfig]) -> None:
        old_ids = set(self._zones.keys())
        new_ids = {z.id for z in zones}
        self._zones = {z.id: z for z in zones}
        for zid in new_ids - old_ids:
            self._zone_states[zid] = ZoneState()
        for zid in old_ids - new_ids:
            self._zone_states.pop(zid, None)
        logger.info("🗺  ZoneTracker[{}] reloaded — {} zones", self.camera_id, len(zones))

    def update(
        self,
        tracks: list[Any],
        known_identities: dict[str, dict[str, Any]],
    ) -> list[SentinelEvent]:
        """Called per frame. Returns zone-related events to publish."""
        if not self._zones:
            return []

        now_ms = time.time() * 1000
        events: list[SentinelEvent] = []
        current_track_ids: set[str] = set()

        for track in tracks:
            track_id = str(track.track_id)
            cx, cy = track.cx, track.cy
            current_track_ids.add(track_id)

            identity = known_identities.get(track_id, {})
            category = identity.get("category", "new")
            person_id = identity.get("person_id")
            person_name = identity.get("name")
            is_staff = category == "staff"

            if track_id not in self._track_zones:
                self._track_zones[track_id] = {}
                self._track_first_seen[track_id] = now_ms

            for zone_id, zone_cfg in self._zones.items():
                state = self._zone_states[zone_id]
                in_zone = _point_in_polygon(cx, cy, zone_cfg.polygon)
                was_in_zone = zone_id in self._track_zones[track_id]

                if in_zone and not was_in_zone:
                    self._track_zones[track_id][zone_id] = now_ms
                    if is_staff:
                        state.staff_tracks.add(track_id)
                        state.last_staff_seen_ms = now_ms
                    else:
                        state.client_tracks.add(track_id)

                    events.append(SentinelEvent(
                        type=EventType.ZONE_ENTERED,
                        camera_id=self.camera_id,
                        location_id=self.location_id,
                        tenant_id=self.tenant_id,
                        track_id=track_id,
                        person_id=person_id,
                        payload={
                            "zone_id": zone_id,
                            "zone_name": zone_cfg.name,
                            "zone_type": zone_cfg.zone_type,
                            "category": category,
                            **({"name": person_name} if person_name else {}),
                        },
                    ))

                elif not in_zone and was_in_zone:
                    entered_at = self._track_zones[track_id].pop(zone_id)
                    dwell_s = round((now_ms - entered_at) / 1000, 1)
                    state.staff_tracks.discard(track_id)
                    state.client_tracks.discard(track_id)
                    state.alerted_client_tracks.discard(track_id)

                    events.append(SentinelEvent(
                        type=EventType.ZONE_EXITED,
                        camera_id=self.camera_id,
                        location_id=self.location_id,
                        tenant_id=self.tenant_id,
                        track_id=track_id,
                        person_id=person_id,
                        payload={
                            "zone_id": zone_id,
                            "zone_name": zone_cfg.name,
                            "zone_type": zone_cfg.zone_type,
                            "dwell_seconds": dwell_s,
                            **({"name": person_name} if person_name else {}),
                        },
                    ))

                elif in_zone and is_staff:
                    state.last_staff_seen_ms = now_ms

        # Clean up departed tracks
        departed = set(self._track_zones.keys()) - current_track_ids
        for tid in departed:
            for zone_id in list(self._track_zones.get(tid, {}).keys()):
                st = self._zone_states.get(zone_id)
                if st:
                    st.staff_tracks.discard(tid)
                    st.client_tracks.discard(tid)
                    st.alerted_client_tracks.discard(tid)
            self._track_zones.pop(tid, None)
            self._track_first_seen.pop(tid, None)

        # --- Business rules ---
        events.extend(self._check_staff_absence(now_ms))
        events.extend(self._check_unattended_clients(now_ms, tracks, known_identities))

        return events

    def _check_staff_absence(self, now_ms: float) -> list[SentinelEvent]:
        events: list[SentinelEvent] = []
        for zone_id, zone_cfg in self._zones.items():
            if not zone_cfg.staff_required:
                continue
            state = self._zone_states[zone_id]
            if state.staff_tracks:
                state.last_staff_seen_ms = now_ms
                continue
            if state.last_staff_seen_ms == 0:
                state.last_staff_seen_ms = now_ms
                continue

            absence_s = (now_ms - state.last_staff_seen_ms) / 1000
            if absence_s < zone_cfg.max_absence_seconds:
                continue

            cooldown_elapsed = (now_ms - state.last_absence_alert_ms) / 1000
            if cooldown_elapsed < ALERT_COOLDOWN_SECONDS:
                continue

            state.last_absence_alert_ms = now_ms
            absence_min = round(absence_s / 60, 1)
            events.append(SentinelEvent(
                type=EventType.STAFF_ABSENT,
                camera_id=self.camera_id,
                location_id=self.location_id,
                tenant_id=self.tenant_id,
                payload={
                    "zone_id": zone_id,
                    "zone_name": zone_cfg.name,
                    "zone_type": zone_cfg.zone_type,
                    "absence_minutes": absence_min,
                    "description": f"Персонал отсутствует в зоне «{zone_cfg.name}» уже {absence_min} мин",
                },
            ))
        return events

    def _check_unattended_clients(
        self,
        now_ms: float,
        tracks: list[Any],
        known_identities: dict[str, dict[str, Any]],
    ) -> list[SentinelEvent]:
        events: list[SentinelEvent] = []
        staff_positions: list[tuple[float, float]] = []
        for t in tracks:
            tid = str(t.track_id)
            cat = known_identities.get(tid, {}).get("category", "new")
            if cat == "staff":
                staff_positions.append((t.cx, t.cy))

        for zone_id, zone_cfg in self._zones.items():
            if zone_cfg.zone_type not in ("waiting", "entrance", "reception"):
                continue
            state = self._zone_states[zone_id]

            for t in tracks:
                tid = str(t.track_id)
                cat = known_identities.get(tid, {}).get("category", "new")
                if cat == "staff":
                    continue
                if tid not in state.client_tracks:
                    continue
                if tid in state.alerted_client_tracks:
                    continue

                entered_at = self._track_zones.get(tid, {}).get(zone_id)
                if not entered_at:
                    continue
                wait_s = (now_ms - entered_at) / 1000
                if wait_s < zone_cfg.max_wait_seconds:
                    continue

                staff_nearby = any(
                    _distance(t.cx, t.cy, sx, sy) < PROXIMITY_THRESHOLD_PX
                    for sx, sy in staff_positions
                )
                if staff_nearby:
                    continue

                state.alerted_client_tracks.add(tid)
                wait_min = round(wait_s / 60, 1)
                events.append(SentinelEvent(
                    type=EventType.CLIENT_UNATTENDED,
                    camera_id=self.camera_id,
                    location_id=self.location_id,
                    tenant_id=self.tenant_id,
                    track_id=tid,
                    person_id=known_identities.get(tid, {}).get("person_id"),
                    payload={
                        "zone_id": zone_id,
                        "zone_name": zone_cfg.name,
                        "zone_type": zone_cfg.zone_type,
                        "wait_minutes": wait_min,
                        "description": f"Клиент ожидает в «{zone_cfg.name}» {wait_min} мин без внимания персонала",
                    },
                ))
        return events


async def load_zones_for_camera(camera_id: str) -> list[ZoneConfig]:
    """Load active zones from DB for a given camera."""
    from sentinel.db.base import AsyncSessionLocal
    from sentinel.db.models.zone import Zone
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(Zone).where(Zone.camera_id == camera_id, Zone.is_active == True)  # noqa: E712
        )).scalars().all()

    configs: list[ZoneConfig] = []
    for z in rows:
        try:
            poly = [(int(p[0]), int(p[1])) for p in json.loads(z.polygon)]
        except (json.JSONDecodeError, IndexError, TypeError):
            logger.warning("Invalid polygon for zone {} — skipping", z.id)
            continue
        configs.append(ZoneConfig(
            id=z.id,
            name=z.name,
            zone_type=z.zone_type,
            polygon=poly,
            staff_required=z.staff_required,
            max_absence_seconds=z.max_absence_seconds,
            max_wait_seconds=z.max_wait_seconds,
        ))
    return configs
