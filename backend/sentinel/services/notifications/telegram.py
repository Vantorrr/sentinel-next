"""
Telegram bot for salon managers — notifications + interactive UI.

Access model:
  - Without linked API key → only /start + key prompt (no alerts, no history)
  - /start <tenant_api_key> → binds this chat to the salon
  - Then: keyboard (status / history / alerts / help / unlink) + push alerts

Requires TELEGRAM_BOT_TOKEN in env.
"""

from __future__ import annotations

import asyncio
import html
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import select, update

from sentinel.core.config import get_settings
from sentinel.core.events import EventBus, EventType, SentinelEvent
from sentinel.db.base import AsyncSessionLocal
from sentinel.db.models.person import Alert, NarrativeSummary
from sentinel.db.models.tenant import Tenant
from sentinel.services.llm.redbook import (
    RedBookRemark,
    format_telegram_remark,
    remark_guest_unattended,
    remark_staff_absent,
)

cfg = get_settings()

ALERT_TYPES = {
    EventType.STAFF_ABSENT,
    EventType.CLIENT_UNATTENDED,
    EventType.ZONE_VIOLATION,
    EventType.FRAUD_ALERT,
}

RATE_LIMIT_CRITICAL = 60
RATE_LIMIT_DEFAULT = 180

# Reply keyboard labels (must match handlers)
BTN_STATUS = "📊 Статус"
BTN_HISTORY = "📋 История"
BTN_ALERTS = "🔔 Алерты"
BTN_SUMMARY = "🗒 Сводка"
BTN_HELP = "ℹ️ Помощь"
BTN_UNLINK = "🔓 Отвязать"

MAIN_KEYBOARD: dict[str, Any] = {
    "keyboard": [
        [{"text": BTN_STATUS}, {"text": BTN_ALERTS}],
        [{"text": BTN_HISTORY}, {"text": BTN_SUMMARY}],
        [{"text": BTN_HELP}, {"text": BTN_UNLINK}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}

REMOVE_KEYBOARD: dict[str, Any] = {"remove_keyboard": True}

WELCOME_GUEST = (
    "🛡 <b>SENTINEL</b> · контроль салона\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "Добро пожаловать.\n"
    "Я присылаю замечания <b>Красной книги</b>, тревоги зон "
    "и краткие сводки по вашему салону.\n\n"
    "🔒 Доступ только по API-ключу салона.\n"
    "Без ключа уведомления и история недоступны.\n\n"
    "<b>Подключение:</b>\n"
    "<code>/start ВАШ_API_КЛЮЧ</code>\n\n"
    "Ключ — в кабинете суперадмина → карточка салона → API key.\n\n"
    "<i>Конфиденциально. Один чат — один салон.</i>"
)

WELCOME_LINKED = (
    "✅ Салон <b>{name}</b> подключён.\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "Теперь вы будете получать:\n"
    "• замечания Красной книги (гость без встречи, пустой ресепшен)\n"
    "• тревоги зон и fraud\n"
    "• сводки по запросу\n\n"
    "Используйте кнопки ниже или команды:\n"
    "/status · /alerts · /history · /summary · /help · /unlink"
)


class TelegramNotifier:
    def __init__(self) -> None:
        self._bus = EventBus.get()
        self._token = cfg.TELEGRAM_BOT_TOKEN
        self._client: Any = None
        # tenant_id -> chat_id
        self._chat_ids: dict[str, str] = {}
        # chat_id -> tenant_id (auth gate)
        self._chat_to_tenant: dict[str, str] = {}
        self._tenant_names: dict[str, str] = {}
        self._chat_ids_loaded_at: float = 0
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

        await self._load_chat_ids(force=True)
        me = await self._api("getMe")
        bot_name = (me or {}).get("result", {}).get("username", "?")
        logger.info("📱 Telegram bot @{} ready (linked salons={})", bot_name, len(self._chat_ids))

        q = self._bus.subscribe()
        try:
            while True:
                await self._poll_updates()
                try:
                    event = await asyncio.wait_for(q.get(), timeout=2.0)
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

    # ── Auth / tenant binding ─────────────────────────────────────────────────

    async def _load_chat_ids(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._chat_ids_loaded_at < 60:
            return
        try:
            async with AsyncSessionLocal() as session:
                rows = (await session.execute(
                    select(Tenant.id, Tenant.telegram_chat_id, Tenant.name)
                    .where(Tenant.telegram_chat_id != None, Tenant.is_active == True)  # noqa: E711, E712
                )).all()
            self._chat_ids = {r[0]: r[1] for r in rows if r[1]}
            self._tenant_names = {r[0]: r[2] for r in rows}
            self._chat_to_tenant = {cid: tid for tid, cid in self._chat_ids.items()}
            self._chat_ids_loaded_at = now
        except Exception as exc:
            logger.warning("Telegram: failed to load chat_ids: {}", exc)

    def _tenant_for_chat(self, chat_id: str) -> str | None:
        return self._chat_to_tenant.get(chat_id)

    async def _deny(self, chat_id: str) -> None:
        await self._send_message(
            chat_id,
            "🔒 Сначала подключите салон.\n\n"
            "Отправьте:\n<code>/start ВАШ_API_КЛЮЧ</code>\n\n"
            "Ключ выдаёт суперадмин в карточке салона.",
            reply_markup=REMOVE_KEYBOARD,
        )

    # ── Alerts push ───────────────────────────────────────────────────────────

    def _remark_from_event(self, event: SentinelEvent) -> RedBookRemark | None:
        payload = event.payload or {}
        if payload.get("remark_code") and payload.get("description"):
            return RedBookRemark(
                code=str(payload.get("remark_code")),
                chapter=str(payload.get("chapter", "Красная книга")),
                title=str(payload.get("title", "Замечание")),
                severity=str(payload.get("severity", "high")),  # type: ignore[arg-type]
                description=str(payload.get("description")),
                action=str(payload.get("action", "Проверить салон.")),
                telegram_emoji=str(payload.get("telegram_emoji", "🟠")),
            )
        zone = str(payload.get("zone_name", "зона"))
        if event.type == EventType.CLIENT_UNATTENDED:
            return remark_guest_unattended(
                zone_name=zone,
                wait_min=float(payload.get("wait_minutes", 1)),
            )
        if event.type == EventType.STAFF_ABSENT:
            return remark_staff_absent(
                zone_name=zone,
                absence_min=float(payload.get("absence_minutes", 3)),
            )
        return None

    async def _handle_alert(self, event: SentinelEvent) -> None:
        await self._load_chat_ids()

        tenant_id = event.tenant_id
        chat_id = self._chat_ids.get(tenant_id)
        if not chat_id:
            return

        remark = self._remark_from_event(event)
        severity = (remark.severity if remark else "medium")
        cooldown = RATE_LIMIT_CRITICAL if severity in ("critical", "high") else RATE_LIMIT_DEFAULT

        rate_key = (tenant_id, f"{event.type}:{event.payload.get('zone_id', '')}")
        now = time.time()
        last = self._rate_limits.get(rate_key, 0)
        if now - last < cooldown:
            return
        self._rate_limits[rate_key] = now

        tenant_name = self._tenant_names.get(tenant_id, "")
        ts = time.strftime("%H:%M", time.localtime(event.timestamp_ms / 1000))

        if remark:
            text = format_telegram_remark(
                remark,
                tenant_name=tenant_name,
                camera_id=event.camera_id,
                time_str=ts,
            )
        else:
            description = event.payload.get("description", str(event.type))
            emoji = "🔴" if event.type in (EventType.FRAUD_ALERT, EventType.STAFF_ABSENT) else "🟠"
            text = (
                f"{emoji} <b>SENTINEL</b>"
                + (f" | {html.escape(tenant_name)}" if tenant_name else "")
                + f"\n\n{html.escape(str(description))}"
                + (f"\n\n📷 Камера: {html.escape(event.camera_id)}" if event.camera_id != "__system__" else "")
                + f" | {ts}"
            )

        await self._send_message(chat_id, text, reply_markup=MAIN_KEYBOARD)

    # ── Telegram API ──────────────────────────────────────────────────────────

    async def _api(self, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if not self._client:
            return None
        url = f"https://api.telegram.org/bot{self._token}/{method}"
        try:
            if payload is None:
                resp = await self._client.get(url)
            else:
                resp = await self._client.post(url, json=payload)
            if resp.status_code != 200:
                logger.warning("Telegram {} failed ({}): {}", method, resp.status_code, resp.text[:200])
                return None
            return resp.json()
        except Exception as exc:
            logger.warning("Telegram {} error: {}", method, exc)
            return None

    async def _send_message(
        self,
        chat_id: str,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        body: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            body["reply_markup"] = reply_markup
        await self._api("sendMessage", body)

    async def _answer_callback(self, callback_id: str, text: str = "") -> None:
        await self._api("answerCallbackQuery", {
            "callback_query_id": callback_id,
            "text": text[:200] if text else "",
        })

    # ── Updates / commands ────────────────────────────────────────────────────

    async def _poll_updates(self) -> None:
        data = await self._api("getUpdates", {
            "offset": self._last_update_id + 1,
            "timeout": 0,
            "allowed_updates": ["message", "callback_query"],
        })
        if not data:
            return
        for update in data.get("result", []):
            self._last_update_id = max(self._last_update_id, update["update_id"])
            try:
                if "callback_query" in update:
                    await self._handle_callback(update["callback_query"])
                elif "message" in update:
                    await self._handle_message(update["message"])
            except Exception as exc:
                logger.warning("Telegram update handler error: {}", exc)

    async def _handle_callback(self, cb: dict[str, Any]) -> None:
        chat = cb.get("message", {}).get("chat", {})
        chat_id = str(chat.get("id", ""))
        data = str(cb.get("data", ""))
        cb_id = str(cb.get("id", ""))
        if not chat_id:
            return

        tenant_id = self._tenant_for_chat(chat_id)
        if not tenant_id:
            await self._answer_callback(cb_id, "Нужна авторизация")
            await self._deny(chat_id)
            return

        await self._answer_callback(cb_id)
        if data == "alerts":
            await self._cmd_alerts(chat_id, tenant_id)
        elif data == "history":
            await self._cmd_history(chat_id, tenant_id)
        elif data == "status":
            await self._cmd_status(chat_id, tenant_id)
        elif data == "summary":
            await self._cmd_summary(chat_id, tenant_id)

    async def _handle_message(self, msg: dict[str, Any]) -> None:
        text = (msg.get("text") or "").strip()
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if not chat_id or not text:
            return

        # Always allow /start (with or without key)
        if text.startswith("/start"):
            await self._cmd_start(chat_id, text)
            return

        tenant_id = self._tenant_for_chat(chat_id)
        if not tenant_id:
            # Also accept bare API key paste
            if text.startswith("sk-") and len(text) > 20:
                await self._cmd_start(chat_id, f"/start {text}")
                return
            await self._deny(chat_id)
            return

        cmd = text.split()[0].lower().split("@")[0]
        if cmd in ("/status",) or text == BTN_STATUS:
            await self._cmd_status(chat_id, tenant_id)
        elif cmd in ("/alerts",) or text == BTN_ALERTS:
            await self._cmd_alerts(chat_id, tenant_id)
        elif cmd in ("/history",) or text == BTN_HISTORY:
            await self._cmd_history(chat_id, tenant_id)
        elif cmd in ("/summary",) or text == BTN_SUMMARY:
            await self._cmd_summary(chat_id, tenant_id)
        elif cmd in ("/help",) or text == BTN_HELP:
            await self._cmd_help(chat_id, tenant_id)
        elif cmd in ("/unlink",) or text == BTN_UNLINK:
            await self._cmd_unlink(chat_id, tenant_id)
        else:
            await self._send_message(
                chat_id,
                "Команда не распознана. Нажмите кнопку меню или /help",
                reply_markup=MAIN_KEYBOARD,
            )

    async def _cmd_start(self, chat_id: str, text: str) -> None:
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            # Already linked? Show menu
            await self._load_chat_ids()
            tid = self._tenant_for_chat(chat_id)
            if tid:
                name = html.escape(self._tenant_names.get(tid, "салон"))
                await self._send_message(
                    chat_id,
                    f"С возвращением. Салон <b>{name}</b> уже подключён.\n"
                    "Выберите действие на клавиатуре.",
                    reply_markup=MAIN_KEYBOARD,
                )
            else:
                await self._send_message(chat_id, WELCOME_GUEST, reply_markup=REMOVE_KEYBOARD)
            return

        api_key = parts[1].strip()
        async with AsyncSessionLocal() as session:
            tenant = (await session.execute(
                select(Tenant).where(Tenant.api_key == api_key, Tenant.is_active == True)  # noqa: E712
            )).scalar_one_or_none()
            if not tenant:
                await self._send_message(
                    chat_id,
                    "❌ Неверный или неактивный API-ключ.\n"
                    "Проверьте ключ в карточке салона и попробуйте снова:\n"
                    "<code>/start sk-…</code>",
                    reply_markup=REMOVE_KEYBOARD,
                )
                return

            # Unbind this chat from any other tenant first
            await session.execute(
                update(Tenant)
                .where(Tenant.telegram_chat_id == chat_id)
                .values(telegram_chat_id=None)
            )
            await session.execute(
                update(Tenant).where(Tenant.id == tenant.id).values(telegram_chat_id=chat_id)
            )
            await session.commit()

        await self._load_chat_ids(force=True)
        await self._send_message(
            chat_id,
            WELCOME_LINKED.format(name=html.escape(tenant.name)),
            reply_markup=MAIN_KEYBOARD,
        )
        logger.info("Telegram linked tenant={} chat={}", tenant.id, chat_id)

    async def _cmd_help(self, chat_id: str, tenant_id: str) -> None:
        name = html.escape(self._tenant_names.get(tenant_id, ""))
        await self._send_message(
            chat_id,
            f"ℹ️ <b>Справка · {name}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "<b>Кнопки</b>\n"
            f"{BTN_STATUS} — камеры и связь\n"
            f"{BTN_ALERTS} — последние тревоги\n"
            f"{BTN_HISTORY} — история замечаний\n"
            f"{BTN_SUMMARY} — последние AI-сводки\n"
            f"{BTN_UNLINK} — отвязать этот чат\n\n"
            "<b>Команды</b>\n"
            "/status /alerts /history /summary /unlink\n\n"
            "Уведомления приходят автоматически при событиях Красной книги.",
            reply_markup=MAIN_KEYBOARD,
        )

    async def _cmd_status(self, chat_id: str, tenant_id: str) -> None:
        from sentinel.pipeline.manager import get_manager

        manager = get_manager()
        cams = [c for c in manager.list_cameras() if c.get("tenant_id") == tenant_id]
        running = sum(1 for c in cams if c.get("running"))
        name = html.escape(self._tenant_names.get(tenant_id, "Салон"))

        lines = [
            f"📊 <b>Статус · {name}</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"📷 Камеры: <b>{running}/{len(cams)}</b> активны",
            f"🔗 Telegram: подключён",
            f"🕒 {time.strftime('%d.%m.%Y %H:%M')}",
        ]
        if cams:
            lines.append("")
            for c in cams[:12]:
                mark = "🟢" if c.get("running") else "⚪"
                lines.append(f"{mark} {html.escape(str(c.get('name') or c.get('id')))}")
        else:
            lines.append("\nКамер пока нет — добавьте в кабинете Sentinel.")

        await self._send_message(chat_id, "\n".join(lines), reply_markup=MAIN_KEYBOARD)

    async def _cmd_alerts(self, chat_id: str, tenant_id: str) -> None:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(
                select(Alert)
                .where(Alert.tenant_id == tenant_id, Alert.created_at >= since)
                .order_by(Alert.created_at.desc())
                .limit(15)
            )).scalars().all()

        name = html.escape(self._tenant_names.get(tenant_id, "Салон"))
        if not rows:
            await self._send_message(
                chat_id,
                f"🔔 <b>Алерты · {name}</b>\n\nЗа последние 24 ч тревог нет.",
                reply_markup=MAIN_KEYBOARD,
            )
            return

        lines = [f"🔔 <b>Алерты · {name}</b> (24 ч)", "━━━━━━━━━━━━━━━━━━━━", ""]
        for a in rows:
            ts = a.created_at.astimezone().strftime("%d.%m %H:%M") if a.created_at else ""
            sev = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(
                (a.severity or "").lower(), "⚪"
            )
            desc = html.escape((a.description or a.type or "")[:120])
            lines.append(f"{sev} <b>{ts}</b>\n{desc}\n")

        await self._send_message(chat_id, "\n".join(lines)[:4000], reply_markup=MAIN_KEYBOARD)

    async def _cmd_history(self, chat_id: str, tenant_id: str) -> None:
        since = datetime.now(timezone.utc) - timedelta(days=7)
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(
                select(Alert)
                .where(Alert.tenant_id == tenant_id, Alert.created_at >= since)
                .order_by(Alert.created_at.desc())
                .limit(25)
            )).scalars().all()

        name = html.escape(self._tenant_names.get(tenant_id, "Салон"))
        if not rows:
            await self._send_message(
                chat_id,
                f"📋 <b>История · {name}</b>\n\nЗа 7 дней записей нет.",
                reply_markup=MAIN_KEYBOARD,
            )
            return

        lines = [f"📋 <b>История · {name}</b> (7 дн.)", "━━━━━━━━━━━━━━━━━━━━", ""]
        for a in rows:
            ts = a.created_at.astimezone().strftime("%d.%m %H:%M") if a.created_at else ""
            lines.append(
                f"• <b>{ts}</b> · <code>{html.escape(a.type)}</code>\n"
                f"  {html.escape((a.description or '')[:100])}\n"
            )

        await self._send_message(chat_id, "\n".join(lines)[:4000], reply_markup=MAIN_KEYBOARD)

    async def _cmd_summary(self, chat_id: str, tenant_id: str) -> None:
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(
                select(NarrativeSummary)
                .where(NarrativeSummary.tenant_id == tenant_id)
                .order_by(NarrativeSummary.created_at.desc())
                .limit(5)
            )).scalars().all()

        name = html.escape(self._tenant_names.get(tenant_id, "Салон"))
        if not rows:
            await self._send_message(
                chat_id,
                f"🗒 <b>Сводка · {name}</b>\n\n"
                "AI-сводок пока нет. Они появятся после событий с камер "
                "(и при настроенном LLM-ключе).",
                reply_markup=MAIN_KEYBOARD,
            )
            return

        lines = [f"🗒 <b>Сводки · {name}</b>", "━━━━━━━━━━━━━━━━━━━━", ""]
        for s in rows:
            ts = s.created_at.astimezone().strftime("%d.%m %H:%M") if s.created_at else ""
            mood = html.escape(s.mood or "—")
            narr = html.escape((s.narrative or "")[:280])
            lines.append(f"<b>{ts}</b> · настроение: {mood}\n{narr}\n")

        await self._send_message(chat_id, "\n".join(lines)[:4000], reply_markup=MAIN_KEYBOARD)

    async def _cmd_unlink(self, chat_id: str, tenant_id: str) -> None:
        name = html.escape(self._tenant_names.get(tenant_id, "салон"))
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(Tenant)
                .where(Tenant.id == tenant_id, Tenant.telegram_chat_id == chat_id)
                .values(telegram_chat_id=None)
            )
            await session.commit()
        await self._load_chat_ids(force=True)
        await self._send_message(
            chat_id,
            f"🔓 Чат отвязан от салона <b>{name}</b>.\n\n"
            "Уведомления больше не приходят.\n"
            "Чтобы подключить снова: <code>/start API_КЛЮЧ</code>",
            reply_markup=REMOVE_KEYBOARD,
        )
        logger.info("Telegram unlinked tenant={} chat={}", tenant_id, chat_id)
