"""
AI Chat Assistant — answers natural-language queries about the surveillance data.

Examples:
  "Кто сегодня заходил из VIP?" → queries DB → formats response
  "Сколько клиентов было вчера в 15:00?" → time-series query
  "Есть ли подозрительная активность?" → fraud alerts summary

Uses Claude with tool-calling to dynamically query Postgres.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel.core.config import get_settings
from sentinel.services.llm.redbook import redbook_system_for_chat

cfg = get_settings()

SYSTEM_PROMPT = redbook_system_for_chat()

TOOLS: list[dict[str, Any]] = [
    {
        "name": "query_visits",
        "description": "Получить список посещений за период",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_iso": {"type": "string", "description": "ISO datetime начала"},
                "end_iso": {"type": "string", "description": "ISO datetime конца"},
                "category": {
                    "type": "string",
                    "enum": ["all", "vip", "regular", "new", "staff"],
                    "description": "Категория клиентов",
                },
                "location_id": {"type": "string"},
            },
            "required": ["start_iso", "end_iso"],
        },
    },
    {
        "name": "query_alerts",
        "description": "Получить список алертов безопасности",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_iso": {"type": "string"},
                "severity": {"type": "string", "enum": ["all", "high", "medium", "low"]},
            },
            "required": ["start_iso"],
        },
    },
    {
        "name": "query_occupancy",
        "description": "Средняя заполненность зала по часам",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "location_id": {"type": "string"},
            },
            "required": ["date"],
        },
    },
]


class ChatAssistant:
    def __init__(self, db_session: AsyncSession, tenant_id: str = "legacy") -> None:
        self._session = db_session
        self._tenant_id = tenant_id
        self._provider = cfg.LLM_PROVIDER
        self._or_key = (cfg.OPENROUTER_API_KEY or "").strip()
        self._oa_key = (cfg.OPENAI_API_KEY or "").strip()
        self._ant_key = (cfg.ANTHROPIC_API_KEY or "").strip()
        if self._or_key or self._provider == "openrouter":
            self._provider = "openrouter"
        elif self._provider == "openai" and self._oa_key:
            self._provider = "openai"
        elif self._ant_key:
            self._provider = "anthropic"
        elif self._oa_key:
            self._provider = "openai"

    async def ask(self, question: str, history: list[dict[str, str]] | None = None) -> str:
        if self._provider == "anthropic" and not self._ant_key:
            return "LLM не настроен — задайте OPENROUTER_API_KEY или ANTHROPIC_API_KEY."
        if self._provider in ("openai", "openrouter") and not (self._or_key or self._oa_key):
            return "LLM не настроен — задайте OPENROUTER_API_KEY или OPENAI_API_KEY."

        try:
            if self._provider in ("openai", "openrouter"):
                return await self._ask_openai_compatible(question, history)
            return await self._ask_anthropic(question, history)
        except Exception as exc:
            logger.error("Chat LLM error: {}", exc)
            return "Ошибка связи с AI: сервис временно недоступен. Попробуйте позже."

    async def _ask_openai_compatible(
        self, question: str, history: list[dict[str, str]] | None = None
    ) -> str:
        from openai import AsyncOpenAI

        kwargs: dict[str, str] = {"api_key": self._or_key or self._oa_key}
        base = (cfg.OPENAI_BASE_URL or "").strip()
        if self._provider == "openrouter" or self._or_key or "openrouter.ai" in base:
            kwargs["base_url"] = base or "https://openrouter.ai/api/v1"
        elif base:
            kwargs["base_url"] = base
        client = AsyncOpenAI(**kwargs)

        model = cfg.LLM_MODEL
        if "claude" in model.lower() and "/" not in model:
            model = "openai/gpt-4o-mini"

        messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for m in history or []:
            if m.get("role") in ("user", "assistant") and m.get("content"):
                messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user", "content": question})

        resp = await client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=1024,
        )
        return (resp.choices[0].message.content or "").strip() or "Нет данных."

    async def _ask_anthropic(self, question: str, history: list[dict[str, str]] | None = None) -> str:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=self._ant_key)
        messages: list[dict[str, Any]] = list(history or [])
        messages.append({"role": "user", "content": question})

        for _ in range(5):
            resp = await client.messages.create(
                model=cfg.LLM_MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=TOOLS,  # type: ignore[arg-type]
                messages=messages,
            )

            if resp.stop_reason == "end_turn":
                for block in resp.content:
                    if hasattr(block, "text"):
                        return block.text  # type: ignore[return-value]
                return "Нет данных."

            tool_results = []
            for block in resp.content:
                if block.type != "tool_use":  # type: ignore[union-attr]
                    continue
                result = await self._execute_tool(block.name, block.input)  # type: ignore[union-attr]
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,  # type: ignore[union-attr]
                    "content": json.dumps(result, ensure_ascii=False),
                })

            messages.append({"role": "assistant", "content": resp.content})  # type: ignore[arg-type]
            messages.append({"role": "user", "content": tool_results})

        return "Превышен лимит вызовов инструментов."

    async def _execute_tool(self, name: str, args: dict[str, Any]) -> Any:
        from sentinel.db.queries.analytics import get_alerts, get_occupancy_by_hour, get_visits
        if name == "query_visits":
            return await get_visits(self._session, self._tenant_id, **args)
        if name == "query_alerts":
            return await get_alerts(self._session, self._tenant_id, **args)
        if name == "query_occupancy":
            return await get_occupancy_by_hour(self._session, self._tenant_id, **args)
        return {"error": f"Unknown tool: {name}"}
