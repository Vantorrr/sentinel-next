#!/usr/bin/env python3
"""
Sentinel-Next — Database Seeder

Создаёт:
  - Тестовых персон в PostgreSQL (Андрей — staff, VIP Клиент, несколько regular)
  - Синтетические face-embeddings в Qdrant (random 512-dim vectors — для тестирования ReID пайплайна)
  - Тестовые визиты и один алерт

Запуск:
  cd sentinel-next
  python seed.py

После запуска seed.py можно открыть http://localhost:3000 и
увидеть наполненную базу данных без необходимости ждать реальных событий.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure backend package is importable
sys.path.insert(0, str(Path(__file__).parent / "backend"))

# Load .env
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")


async def seed() -> None:
    from sentinel.db.base import AsyncSessionLocal, engine, Base
    from sentinel.db.models.person import Alert, NarrativeSummary, Person, PersonCategory, Visit
    from sentinel.core.config import get_settings
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams
    import numpy as np

    cfg = get_settings()

    print("🌱 Sentinel-Next Seeder starting…")

    # ── 1. Create DB tables ──────────────────────────────────────────────────
    print("  → Creating DB tables (if not exist)…")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("  ✅ Tables ready")

    # ── 2. Create persons ─────────────────────────────────────────────────────
    persons_data = [
        {
            "id": "person-andrey-001",
            "name": "Андрей",
            "category": PersonCategory.STAFF,
            "phone": "+7-900-000-0001",
            "notes": "Администратор. Всегда на месте в 9:00.",
            "visit_count": 245,
        },
        {
            "id": "person-vip-002",
            "name": "Иван Петрович",
            "category": PersonCategory.VIP,
            "phone": "+7-900-000-0002",
            "email": "ivan@example.com",
            "notes": "VIP клиент. Заходит по вторникам и пятницам.",
            "visit_count": 38,
        },
        {
            "id": "person-maria-003",
            "name": "Маша",
            "category": PersonCategory.STAFF,
            "phone": "+7-900-000-0003",
            "notes": "Кассир. Дневная смена.",
            "visit_count": 180,
        },
        {
            "id": "person-regular-004",
            "name": "Клиент А",
            "category": PersonCategory.REGULAR,
            "visit_count": 12,
        },
        {
            "id": "person-new-005",
            "name": "Незнакомец",
            "category": PersonCategory.NEW,
            "visit_count": 1,
        },
    ]

    now = datetime.now(tz=timezone.utc)

    async with AsyncSessionLocal() as session:
        for data in persons_data:
            existing = await session.get(Person, data["id"])
            if existing:
                print(f"  ⏭  Person '{data['name']}' already exists — skip")
                continue
            person = Person(
                last_seen=now - timedelta(hours=1),
                first_seen=now - timedelta(days=data["visit_count"]),
                **data,
            )
            session.add(person)
        await session.flush()

        # ── 3. Seed visits ───────────────────────────────────────────────────
        visits = [
            Visit(
                person_id="person-andrey-001",
                location_id="default",
                camera_id="cam-вход",
                track_id="seed-track-001",
                entered_at=now - timedelta(hours=3),
                left_at=now - timedelta(minutes=5),
                dwell_seconds=10500,
            ),
            Visit(
                person_id="person-vip-002",
                location_id="default",
                camera_id="cam-вход",
                track_id="seed-track-002",
                entered_at=now - timedelta(hours=1, minutes=30),
                left_at=now - timedelta(minutes=20),
                dwell_seconds=4200,
            ),
            Visit(
                person_id="person-new-005",
                location_id="default",
                camera_id="cam-зал",
                track_id="seed-track-005",
                entered_at=now - timedelta(minutes=45),
            ),
        ]
        for v in visits:
            session.add(v)

        # ── 4. Seed alerts ────────────────────────────────────────────────────
        alert = Alert(
            type="zone.violation",
            severity="medium",
            camera_id="cam-касса",
            location_id="default",
            description="Незнакомый человек находился у кассы более 5 минут без покупки.",
            acknowledged=False,
        )
        session.add(alert)

        # ── 5. Seed narrative ─────────────────────────────────────────────────
        narrative = NarrativeSummary(
            location_id="default",
            narrative="Андрей на месте с утра, провёл встречу с Иваном Петровичем. "
                      "Маша обслужила 4 клиентов. Один незнакомый тип у кассы — "
                      "предупреждение выслано. В целом день рабочий.",
            occupancy=3,
            mood="нейтральное",
            alerts_json='["Незнакомый у кассы — рекомендую проверить"]',
            insights_json='["Иван Петрович — постоянный клиент, 38 визитов"]',
        )
        session.add(narrative)

        await session.commit()
        print(f"  ✅ {len(persons_data)} персон, {len(visits)} визитов, 1 алерт, 1 нарратив сохранены")

    # ── 6. Seed Qdrant embeddings ─────────────────────────────────────────────
    print("  → Seeding Qdrant face embeddings…")
    try:
        qdrant = AsyncQdrantClient(url=cfg.QDRANT_URL)
        cols = await qdrant.get_collections()
        existing_cols = [c.name for c in cols.collections]

        if cfg.QDRANT_COLLECTION_FACES not in existing_cols:
            await qdrant.create_collection(
                cfg.QDRANT_COLLECTION_FACES,
                vectors_config=VectorParams(size=cfg.QDRANT_VECTOR_SIZE, distance=Distance.COSINE),
            )

        rng = np.random.default_rng(1337)
        points = []
        for person in persons_data:
            # Generate normalised synthetic embedding
            emb = rng.standard_normal(cfg.QDRANT_VECTOR_SIZE).astype(np.float32)
            emb = emb / np.linalg.norm(emb)
            points.append(PointStruct(
                id=str(uuid.uuid4()),
                vector=emb.tolist(),
                payload={
                    "person_id": person["id"],
                    "name": person["name"],
                    "category": person["category"].value
                        if hasattr(person["category"], "value")
                        else str(person["category"]),
                    "visit_count": person["visit_count"],
                },
            ))

        await qdrant.upsert(collection_name=cfg.QDRANT_COLLECTION_FACES, points=points)
        print(f"  ✅ {len(points)} face embeddings seeded in Qdrant")
    except Exception as exc:
        print(f"  ⚠  Qdrant seeding failed (Qdrant might be offline): {exc}")

    print()
    print("🎉 Seeding complete! Start the system:")
    print("   python startup.py")
    print()


if __name__ == "__main__":
    asyncio.run(seed())
