"""
Telegram Notifier — sends zone alerts to salon managers via Telegram Bot API.

Also handles /start <api_key> messages for auto-linking chat_id to tenants.

Lifecycle: started as background task in main.py (only if TELEGRAM_BOT_TOKEN is set).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from loguru import logger
from sqlalchemy import select, update

from sentinel.core.config import get_settings
from sentinel.core.events import EventBus, EventType, SentinelEvent
from sentinel.db.base import AsyncSessionLocal
from sentinel.db.models.tenant import Tenant

cfg = get_settings()

ALERT_TYPES = {
    EventType.STAFF_ABSENT,
    EventType.CLIENT_UNATTENDED,
    EventType.ZONE_VIOLATION,
    EventType.FRAUD_ALERT,
}

RATE_LIMIT_SECONDS = 300  # 5 min per alert type per tenant


class TelegramNotifier:
    def __init__(self) -> None:
        self._bus = EventBus.get()
        self._token = cfg.TELEGRAM_BOT_TOKEN
        self._client: Any = None
        # tenant_id -> telegram_chat_id (cached)
        self._chat_ids: dict[str, str] = {}
        self._chat_ids_loaded_at: float = 0
        # (tenant_id, event_type) -> last_alert_ts
        self._rate_limits: dict[tuple[str, str], float] = {}
        self._last_update_id = 0

    async def run(self) -> None:
        if not self._token:
            logger.info("Telegram: no TELEGRAM_BOT_TOKEN — disabled")
            return

        try:
            import httpx
            self._client = httpx.AsyncClient(timeout=30)
        except ImportError:
            logger.warning("httpx not installed — Telegram disabled")
            return

        logger.info("📱 TelegramNotifier started")

        q = self._bus.subscribe()
        try:
            while True:
                # Poll for bot commands every cycle
                await self._poll_commands()

                try:
                    event = await asyncio.wait_for(q.get(), timeout=10.0)
                    if event.type in ALERT_TYPES:
                        await self._handle_alert(event)
                except TimeoutError:
                    pass
        except asyncio.CancelledError:
            pass
        finally:
            self._bus.unsubscribe(q)
            if self._client:
                await self._client.aclose()

    async def _load_chat_ids(self) -> None:
        now = time.time()
        if now - self._chat_ids_loaded_at < 60:
            return
        try:
            async with AsyncSessionLocal() as session:
                rows = (await session.execute(
                    select(Tenant.id, Tenant.telegram_chat_id, Tenant.name)
                    .where(Tenant.telegram_chat_id != None, Tenant.is_active == True)  # noqa: E711, E712
                )).all()
            self._chat_ids = {r[0]: r[1] for r in rows if r[1]}
            self._tenant_names: dict[str, str] = {r[0]: r[2] for r in rows}
            self._chat_ids_loaded_at = now
        except Exception as exc:
            logger.warning("Telegram: failed to load chat_ids: {}", exc)

    async def _handle_alert(self, event: SentinelEvent) -> None:
        await self._load_chat_ids()

        tenant_id = event.tenant_id
        chat_id = self._chat_ids.get(tenant_id)
        if not chat_id:
            return

        rate_key = (tenant_id, event.type)
        now = time.time()
        last = self._rate_limits.get(rate_key, 0)
        if now - last < RATE_LIMIT_SECONDS:
            return
        self._rate_limits[rate_key] = now

        tenant_name = self._tenant_names.get(tenant_id, "")
        description = event.payload.get("description", str(event.type))
        zone_name = event.payload.get("zone_name", "")
        camera = event.camera_id

        emoji = "🔴" if event.type in (EventType.FRAUD_ALERT, EventType.STAFF_ABSENT) else "🟠"
        ts = time.strftime("%H:%M", time.localtime(event.timestamp_ms / 1000))

        text = (
            f"{emoji} <b>SENTINEL</b>"
            + (f" | {tenant_name}" if tenant_name else "")
            + f"\n\n{description}"
            + (f"\n\n📷 Камера: {camera}" if camera != "__system__" else "")
            + f" | {ts}"
        )

        await self._send_message(chat_id, text)

    async def _send_message(self, chat_id: str, text: str) -> None:
        if not self._client:
            return
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        try:
            resp = await self._client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })
            if resp.status_code != 200:
                logger.warning("Telegram send failed ({}): {}", resp.status_code, resp.text[:200])
        except Exception as exc:
            logger.warning("Telegram send error: {}", exc)

    async def _poll_commands(self) -> None:
        """Check for /start <api_key> messages from new users."""
        if not self._client:
            return
        url = f"https://api.telegram.org/bot{self._token}/getUpdates"
        try:
            resp = await self._client.get(url, params={
                "offset": self._last_update_id + 1,
                "timeout": 0,
                "allowed_updates": '["message"]',
            })
            if resp.status_code != 200:
                return
            data = resp.json()
            for update in data.get("result", []):
                self._last_update_id = max(self._last_update_id, update["update_id"])
                await self._handle_command(update)
        except Exception:
            pass

    async def _handle_command(self, update: dict) -> None:
        msg = update.get("message", {})
        text = msg.get("text", "").strip()
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if not chat_id or not text:
            return

        if text.startswith("/start"):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                await self._send_message(
                    chat_id,
                    "👋 Sentinel Bot\n\nОтправьте <code>/start ВАШ_API_КЛЮЧ</code> чтобы подключить уведомления.\n\nAPI-ключ можно найти в личном кабинете Sentinel.",
                )
                return

            api_key = parts[1].strip()
            await self._link_tenant(chat_id, api_key)

    async def _link_tenant(self, chat_id: str, api_key: str) -> None:
        try:
            async with AsyncSessionLocal() as session:
                tenant = (await session.execute(
                    select(Tenant).where(Tenant.api_key == api_key, Tenant.is_active == True)  # noqa: E712
                )).scalar_one_or_none()

                if not tenant:
                    await self._send_message(chat_id, "❌ Неверный API-ключ. Проверьте ключ в личном кабинете Sentinel.")
                    return

                await session.execute(
                    update(Tenant).where(Tenant.id == tenant.id).values(telegram_chat_id=chat_id)
                )
                await session.commit()

                self._chat_ids[tenant.id] = chat_id
                self._chat_ids_loaded_at = 0  # force reload

                await self._send_message(
                    chat_id,
                    f"✅ Готово! Уведомления для салона <b>«{tenant.name}»</b> подключены.\n\n"
                    f"Вы будете получать алерты когда:\n"
                    f"• Персонал покидает рабочую зону\n"
                    f"• Клиент ждёт без внимания\n"
                    f"• Нарушение зоны доступа",
                )
                logger.info("📱 Telegram linked: tenant={} chat_id={}", tenant.name, chat_id)
        except Exception as exc:
            logger.error("Telegram link error: {}", exc)
            await self._send_message(chat_id, "⚠️ Ошибка при подключении. Попробуйте позже.")
