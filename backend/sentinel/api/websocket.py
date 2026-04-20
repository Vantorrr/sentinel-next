"""
WebSocket event gateway — tenant-isolated.

Clients connect to /ws/events?token=<JWT|API_KEY> and receive
only events belonging to their tenant. Superadmin sees all.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from loguru import logger
from pydantic import BaseModel

from sentinel.core.auth import TenantContext, require_ws_auth
from sentinel.core.events import EventBus, SentinelEvent

router = APIRouter(tags=["websocket"])

SUPERADMIN_TENANT = "__all__"


class ConnectionFilter(BaseModel):
    location_ids: list[str] = []
    event_types: list[str] = []


@router.websocket("/ws/events")
async def events_gateway(
    websocket: WebSocket,
    tenant: TenantContext = Depends(require_ws_auth),
) -> None:
    await websocket.accept()

    bus = EventBus.get()
    q = bus.subscribe()
    filter_cfg = ConnectionFilter()

    client = f"{websocket.client.host}:{websocket.client.port}" if websocket.client else "unknown"
    logger.info("🔌 WS connected: {} (tenant={})", client, tenant.tenant_id)

    async def recv_filter() -> None:
        nonlocal filter_cfg
        while True:
            try:
                raw = await websocket.receive_text()
                data = json.loads(raw)
                filter_cfg = ConnectionFilter(**data)
                logger.debug("WS filter updated: {}", data)
            except Exception:
                break

    recv_task = asyncio.create_task(recv_filter())

    try:
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=30.0)
            except TimeoutError:
                await websocket.send_json({"type": "ping"})
                continue

            # Tenant isolation: only send events belonging to this tenant
            if tenant.tenant_id != SUPERADMIN_TENANT:
                event_tenant = event.tenant_id
                if event_tenant and event_tenant != tenant.tenant_id:
                    continue

            if filter_cfg.location_ids and event.location_id not in filter_cfg.location_ids:
                continue
            if filter_cfg.event_types and event.type not in filter_cfg.event_types:
                continue

            await websocket.send_text(event.to_json())

    except WebSocketDisconnect:
        logger.info("🔌 WS disconnected: {}", client)
    except Exception as exc:
        logger.error("WS error: {}", exc)
    finally:
        recv_task.cancel()
        bus.unsubscribe(q)
