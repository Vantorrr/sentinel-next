"""
Красная книга Вай Тай — operational knowledge + turnkey compliance remarks.

Deterministic rules (zone timers) = exact. LLM narrative = style layer.
We do NOT claim pose/uniform CV at 100% — those need extra models later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Severity = Literal["critical", "high", "medium", "low"]

REDBOOK_CAMERA_RULES = """
СТАНДАРТ ВАЙ ТАЙ (Красная книга) — что оцениваем по камерам:

ГЛАВА 3. ВСТРЕЧА ГОСТЯ
- Любой вошедший = Гость.
- Администратор встречает ТОЛЬКО СТОЯ, выходит навстречу с жестом «вай».
- ЗАПРЕЩЕНО оставаться сидеть за ресепшен, когда Гость вошёл.
- АЛЕРТ: Гость у входа/ресепшен без встречи.
- АЛЕРТ: Администратора нет на ресепшен.

ГЛАВА 1 / 6. ПРОЩАНИЕ И ПОСЛЕ ПРОЦЕДУРЫ
- Провожать до двери: «Ждем вас снова».
- После процедуры чай уже на столе, предложить присесть.
- АЛЕРТ: Гость после процедуры без внимания у ресепшен.

ГЛАВА 11. СМЕНА
- Ресепшен не бросать в рабочие часы.
- АЛЕРТ: ресепшен пуст дольше нормы.
"""

REDBOOK_CHAT_KNOWLEDGE = """
Ты — Sentinel для сети Вай Тай. Судишь сервис по Красной книге Вай Тай.
Отвечай кратко, по делу. Если стандарт нарушен — называй главу и замечание.
Если всё по стандарту — «По Красной книге ок».
"""

REDBOOK_SUMMARY_PROMPT = f"""Ты — Sentinel, доверенный помощник владельца сети «Вай Тай».
Докладывай по стандартам Красной книги.

{REDBOOK_CAMERA_RULES}

Правила:
- 2–4 предложения, живой русский.
- Нарушение = ALERT с главой Красной книги.
- Спокойно и по стандарту — скажи прямо.

Отвечай строго JSON без markdown:
{{
  "narrative": "...",
  "occupancy": <int>,
  "mood": "позитивное|нейтральное|напряжённое",
  "alerts": ["..."],
  "insights": ["..."]
}}"""


@dataclass(frozen=True)
class RedBookRemark:
    code: str
    chapter: str
    title: str
    severity: Severity
    description: str
    action: str
    telegram_emoji: str

    def to_payload(self, **extra: Any) -> dict[str, Any]:
        return {
            "redbook": True,
            "remark_code": self.code,
            "chapter": self.chapter,
            "title": self.title,
            "severity": self.severity,
            "description": self.description,
            "action": self.action,
            "telegram_emoji": self.telegram_emoji,
            **extra,
        }


def remark_guest_unattended(*, zone_name: str, wait_min: float) -> RedBookRemark:
    return RedBookRemark(
        code="RB-CH3-UNATTENDED",
        chapter="Глава 3 — Встреча Гостя",
        title="Гость без встречи",
        severity="critical",
        description=(
            f"Замечание: Гость ждёт в «{zone_name}» уже {wait_min} мин без внимания. "
            f"По Красной книге Администратор обязан встать и выйти навстречу с жестом «вай»."
        ),
        action="Немедленно встретить Гостя стоя у входа/ресепшен. Предложить чай/воду.",
        telegram_emoji="🔴",
    )


def remark_staff_absent(*, zone_name: str, absence_min: float) -> RedBookRemark:
    return RedBookRemark(
        code="RB-CH11-RECEPTION-EMPTY",
        chapter="Глава 3/11 — Ресепшен и смена",
        title="Ресепшен без Администратора",
        severity="high",
        description=(
            f"Замечание: зона «{zone_name}» без персонала {absence_min} мин. "
            f"По Красной книге ресепшен нельзя бросать в рабочие часы."
        ),
        action="Вернуть Администратора на пост. Проверить, есть ли Гости у входа.",
        telegram_emoji="🟠",
    )


def format_telegram_remark(
    remark: RedBookRemark,
    *,
    tenant_name: str = "",
    camera_id: str = "",
    time_str: str = "",
) -> str:
    lines = [
        f"{remark.telegram_emoji} <b>ЗАМЕЧАНИЕ · Красная книга</b>",
    ]
    if tenant_name:
        lines.append(f"Салон: <b>{tenant_name}</b>")
    lines.extend([
        f"<b>{remark.title}</b>",
        f"{remark.chapter}",
        "",
        remark.description,
        "",
        f"✅ Что сделать: {remark.action}",
    ])
    meta = []
    if camera_id and camera_id != "__system__":
        meta.append(f"📷 {camera_id}")
    if time_str:
        meta.append(time_str)
    if meta:
        lines.append("")
        lines.append(" · ".join(meta))
    lines.append(f"\n<code>{remark.code}</code>")
    return "\n".join(lines)


def redbook_system_for_chat() -> str:
    return (
        REDBOOK_CHAT_KNOWLEDGE
        + "\n\n"
        + REDBOOK_CAMERA_RULES
        + "\n\nЕсли нужны данные — вызывай инструменты. Время указывай явно."
    )


# Turnkey zone presets for a typical reception camera (1920x1080 reference).
# User can adjust polygons in UI after apply.
REDBOOK_ZONE_PRESETS: list[dict[str, Any]] = [
    {
        "name": "Вход (Красная книга)",
        "zone_type": "entrance",
        "staff_required": False,
        "max_absence_seconds": 300,
        "max_wait_seconds": 45,
        "polygon": [[40, 200], [700, 200], [700, 1000], [40, 1000]],
        "hint": "Зона двери/входа — Гость должен быть встречен ≤45 сек",
    },
    {
        "name": "Ресепшен (Красная книга)",
        "zone_type": "reception",
        "staff_required": True,
        "max_absence_seconds": 180,
        "max_wait_seconds": 60,
        "polygon": [[720, 180], [1500, 180], [1500, 900], [720, 900]],
        "hint": "Стойка Администратора — staff required, пусто ≤3 мин",
    },
    {
        "name": "Ожидание / чай (Красная книга)",
        "zone_type": "waiting",
        "staff_required": False,
        "max_absence_seconds": 300,
        "max_wait_seconds": 90,
        "polygon": [[1100, 400], [1850, 400], [1850, 1050], [1100, 1050]],
        "hint": "Кресла ожидания — после процедуры чай и внимание",
    },
]

RECEPTION_ZONE_DEFAULTS = {
    "zone_type": "reception",
    "staff_required": True,
    "max_absence_seconds": 180,
    "max_wait_seconds": 60,
}

ENTRANCE_ZONE_DEFAULTS = {
    "zone_type": "entrance",
    "staff_required": False,
    "max_absence_seconds": 300,
    "max_wait_seconds": 45,
}


def scale_preset_polygon(
    polygon: list[list[int]],
    width: int = 1920,
    height: int = 1080,
) -> list[list[int]]:
    """Scale preset from 1920x1080 reference to camera frame size."""
    if width <= 0 or height <= 0:
        return polygon
    sx, sy = width / 1920.0, height / 1080.0
    return [[int(x * sx), int(y * sy)] for x, y in polygon]
