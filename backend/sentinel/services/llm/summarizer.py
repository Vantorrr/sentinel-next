"""
LLM Scene Summarizer — «Голос Лидера».

Батчит сырые события каждые N секунд и звонит LLM за нарративом.
Публикует LLM_SUMMARY обратно в шину → DBWriter сохраняет в Postgres → WebSocket толкает на фронт.

Стиль ответа: дерзкий, честный, как доверенный помощник шефа.
«Сегодня зашло 5 новых девушек, Андрей был на месте, подозрительных типов не зафиксировано».
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from typing import Any

from loguru import logger

from sentinel.core.config import get_settings
from sentinel.core.events import EventBus, EventType, SentinelEvent
from sentinel.services.llm.redbook import REDBOOK_SUMMARY_PROMPT

cfg = get_settings()

# Красная книга Вай Тай — единый стандарт доклада
SYSTEM_PROMPT = REDBOOK_SUMMARY_PROMPT


class SceneSummarizer:
    def __init__(self) -> None:
        self._bus = EventBus.get()
        # Keyed by (tenant_id, location_id)
        self._buffer: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        self._last_summary: dict[tuple[str, str], float] = {}
        self._interval = cfg.LLM_SUMMARIZE_EVERY_SECONDS
        self._anthropic_client = None
        self._openai_client = None
        self._init_clients()

    def _init_clients(self) -> None:
        if cfg.ANTHROPIC_API_KEY:
            try:
                import anthropic
                self._anthropic_client = anthropic.AsyncAnthropic(api_key=cfg.ANTHROPIC_API_KEY)
                logger.info("🧠 LLM: Anthropic Claude configured")
            except ImportError:
                logger.warning("anthropic package not installed")

        if cfg.OPENAI_API_KEY:
            try:
                from openai import AsyncOpenAI
                self._openai_client = AsyncOpenAI(api_key=cfg.OPENAI_API_KEY)
                logger.info("🧠 LLM: OpenAI GPT configured as fallback")
            except ImportError:
                logger.warning("openai package not installed")

        if not self._anthropic_client and not self._openai_client:
            logger.warning("⚠️  No LLM API key set — summaries disabled. Set ANTHROPIC_API_KEY in .env")

    # ── Main loop ──────────────────────────────────────────────────────────────

    async def run(self) -> None:
        q = self._bus.subscribe()
        logger.info("🧠 Summarizer running — interval={}s", self._interval)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=5.0)
                    self._buffer_event(event)
                except TimeoutError:
                    pass

                now = time.time()
                for key, events in list(self._buffer.items()):
                    last = self._last_summary.get(key, 0)
                    if events and (now - last) >= self._interval:
                        tenant_id, location_id = key
                        asyncio.create_task(self._summarize(tenant_id, location_id, list(events)))
                        self._buffer[key].clear()
                        self._last_summary[key] = now
        finally:
            self._bus.unsubscribe(q)

    def _buffer_event(self, event: SentinelEvent) -> None:
        skip = {
            EventType.HEATMAP_UPDATE,
            EventType.OCCUPANCY_UPDATE,
            EventType.PIPELINE_ERROR,
            EventType.LLM_SUMMARY,
        }
        if event.type in skip:
            return

        # Flatten payload for readability
        entry: dict[str, Any] = {
            "type": event.type,
            "camera": event.camera_id,
        }
        if event.track_id:
            entry["track"] = event.track_id
        if event.person_id:
            entry["person_id"] = event.person_id
        if event.payload.get("name"):
            entry["name"] = event.payload["name"]
        if event.payload.get("category"):
            entry["category"] = event.payload["category"]
        if event.payload.get("dwell_seconds"):
            entry["dwell_s"] = event.payload["dwell_seconds"]
        if event.payload.get("zone_name"):
            entry["zone"] = event.payload["zone_name"]
        if event.payload.get("absence_minutes"):
            entry["absence_min"] = event.payload["absence_minutes"]
        if event.payload.get("wait_minutes"):
            entry["wait_min"] = event.payload["wait_minutes"]
        if event.payload.get("description"):
            entry["desc"] = event.payload["description"]
        entry["ts"] = time.strftime("%H:%M:%S", time.localtime(event.timestamp_ms / 1000))

        self._buffer[(event.tenant_id, event.location_id)].append(entry)

    async def _summarize(self, tenant_id: str, location_id: str, events: list[dict[str, Any]]) -> None:
        if not events:
            return
        if not (self._anthropic_client or self._openai_client):
            await self._rule_based_summary(tenant_id, location_id, events)
            return

        # Compact event list for the prompt — no need for full JSON
        lines = []
        for e in events:
            line = f"[{e['ts']}] {e['type']}"
            if e.get("name"):
                line += f" — {e['name']}"
            if e.get("category"):
                line += f" ({e['category']})"
            if e.get("zone"):
                line += f" [зона: {e['zone']}]"
            if e.get("desc"):
                line += f" | {e['desc']}"
            lines.append(line)
        user_msg = (
            f"Локация: {location_id}\n"
            f"Период: последние {self._interval} секунд\n"
            f"Событий: {len(events)}\n\n"
            + "\n".join(lines)
        )

        try:
            raw = await self._call_llm(user_msg)
            raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            parsed = json.loads(raw)
            await self._publish_summary(tenant_id, location_id, parsed, len(events))
        except json.JSONDecodeError:
            logger.warning("LLM returned invalid JSON, using rule-based fallback")
            await self._rule_based_summary(tenant_id, location_id, events)
        except Exception as exc:
            logger.error("❌ Summarizer LLM error for {}: {} — using rule-based fallback", location_id, exc)
            await self._rule_based_summary(tenant_id, location_id, events)

    async def _call_llm(self, user_msg: str) -> str:
        if self._anthropic_client and cfg.LLM_PROVIDER == "anthropic":
            resp = await self._anthropic_client.messages.create(
                model=cfg.LLM_MODEL,
                max_tokens=400,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            return resp.content[0].text  # type: ignore[union-attr]

        if self._openai_client:
            resp = await self._openai_client.chat.completions.create(
                model="gpt-4o-mini",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=400,
            )
            return resp.choices[0].message.content or "{}"

        raise RuntimeError("No LLM provider available")

    async def _rule_based_summary(
        self, tenant_id: str, location_id: str, events: list[dict[str, Any]]
    ) -> None:
        """Fallback summary without LLM — pure logic."""
        entries_count = len(events)
        names = list({e["name"] for e in events if e.get("name")})
        vips = [e for e in events if e.get("category") == "vip"]
        alert_types = {"alert", "violation", "absent", "unattended"}
        alerts = [e for e in events if any(k in e.get("type", "").lower() for k in alert_types)]
        new_clients = len([e for e in events if e.get("category") == "new" and "entered" in e.get("type", "")])
        staff_absent = [e for e in events if e.get("type") == "staff.absent"]
        unattended = [e for e in events if e.get("type") == "client.unattended"]

        parts: list[str] = []
        if staff_absent:
            desc = staff_absent[0].get("desc", "Красная книга: ресепшен без Администратора")
            parts.append(f"⚠ {desc}.")
        if unattended:
            desc = unattended[0].get("desc", "Красная книга гл.3: Гость без встречи")
            parts.append(f"⚠ {desc}.")
        if names:
            parts.append(f"{', '.join(names[:3])} {'на месте' if len(names) == 1 else 'замечены'}.")
        if new_clients:
            parts.append(f"Новых Гостей: {new_clients}.")
        if vips:
            parts.append("VIP-Гость зафиксирован.")
        if alerts and not staff_absent and not unattended:
            parts.append(f"⚠ Нарушения стандартов Красной книги: {len(alerts)}.")
        if not parts:
            parts.append(f"По Красной книге спокойно. Событий: {entries_count}.")

        narrative = " ".join(parts)
        mood = "напряжённое" if (alerts or staff_absent or unattended) else ("позитивное" if vips else "нейтральное")

        await self._publish_summary(tenant_id, location_id, {
            "narrative": narrative,
            "occupancy": len({e.get("track") for e in events if e.get("track")}),
            "mood": mood,
            "alerts": [e.get("type", "") for e in alerts],
            "insights": [],
        }, entries_count)

    async def _publish_summary(
        self, tenant_id: str, location_id: str, parsed: dict[str, Any], event_count: int
    ) -> None:
        await self._bus.publish(SentinelEvent(
            type=EventType.LLM_SUMMARY,
            camera_id="__system__",
            location_id=location_id,
            tenant_id=tenant_id,
            payload={
                "narrative": parsed.get("narrative", ""),
                "occupancy": parsed.get("occupancy", 0),
                "mood": parsed.get("mood", "нейтральное"),
                "alerts": parsed.get("alerts", []),
                "insights": parsed.get("insights", []),
                "event_count": event_count,
            },
        ))
        logger.opt(colors=True).info(
            "🧠 [<magenta>LLM</magenta>] {} | mood={} | {}",
            location_id,
            parsed.get("mood"),
            parsed.get("narrative", "")[:100],
        )
