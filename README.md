# Sentinel-Next v2026

> **Decentralized AI Surveillance & Business Intelligence Platform**

Production-grade, event-driven AI system for salons and retail: analyzes live video, classifies visitors (new / VIP / staff), detects zone violations, sends Telegram alerts, and delivers LLM-powered narratives via a PWA dashboard.

---

## Architecture

```
  RTSP / Hik-Connect cameras ──▶  Pipeline Manager (per-camera)
  (100+ sources)                  ┌─────────────────────────┐
                                  │ PyAV Hardware Decode     │
                                  │ YOLOv11 (MPS/CUDA/CPU)  │
                                  │ ByteTrack Tracking       │
                                  │ InsightFace ReID         │
                                  │ ZoneTracker (proximity)  │
                                  └───────────┬─────────────┘
                                              │ SentinelEvents
                                  ┌───────────▼──────────────┐
                                  │   Redis Event Bus        │
                                  └───────────┬──────────────┘
                       ┌──────────────────────┼──────────────────┐
                       │                      │                   │
            ┌──────────▼──────┐    ┌──────────▼──────┐   ┌───────▼───────┐
            │ LLM Summarizer  │    │ PostgreSQL 16   │   │ Qdrant Vector │
            │ (Claude 3.5)    │    │ Visits/Alerts/  │   │ Face 512-d    │
            │                 │    │ Cameras/Zones   │   │ Embeddings    │
            └────────┬────────┘    └─────────────────┘   └───────────────┘
                     │
            ┌────────▼──────────────────────────┐
            │  FastAPI WS Gateway + REST API     │
            │  /ws/events → Next.js 15 PWA       │
            │    - Real-time feed & heatmaps     │
            │    - AI chat (text + voice)        │
            │    - Zone management               │
            │                                    │
            │  Telegram Bot → Admin alerts       │
            └────────────────────────────────────┘
```

## Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | FastAPI 0.115 · Python 3.11 · Uvicorn |
| **Video** | PyAV (FFmpeg) · Hikvision/Dahua RTSP |
| **Detection** | YOLOv11 (Ultralytics) · MPS/CUDA/CPU |
| **Tracking** | ByteTrack via `supervision` |
| **Face ReID** | InsightFace ArcFace 512-dim → Qdrant |
| **LLM** | Claude 3.5 Sonnet / GPT-4o-mini |
| **Zones** | Point-in-polygon + proximity detection |
| **Alerts** | Telegram Bot API |
| **Database** | PostgreSQL 16 + SQLAlchemy async |
| **Event Bus** | Redis pub/sub |
| **Frontend** | Next.js 15 · Tailwind v4 · Three.js |
| **State** | Zustand · WebSocket real-time |
| **Charts** | Recharts · Framer Motion |
| **Infra** | Docker Compose · Nginx · Railway |

---

## Quick Start (Local Dev)

### Prerequisites
- Python 3.11+, Node.js 22+
- Docker & Docker Compose

```bash
# 1. Clone & configure
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY and SECRET_KEY

# 2. Start infrastructure (Postgres + Redis + Qdrant)
docker compose --profile local up postgres redis qdrant -d

# 3. Backend
cd backend
pip install -e .
alembic upgrade head
uvicorn sentinel.main:app --reload --port 8000

# 4. Frontend
cd ../frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

Default login: `admin@sentinel.ai` / `admin`

---

## Docker (Full Stack — Local)

```bash
cp .env.example .env
# Fill in API keys

docker compose --profile local up --build
```

- **Dashboard**: http://localhost
- **API Docs**: http://localhost/docs

---

## Railway Deployment

Railway provides Postgres as a managed plugin — no need to self-host.

### Step 1: Create Railway project

1. Go to [railway.app](https://railway.app), create a new project
2. Add **PostgreSQL** plugin → Railway auto-sets `DATABASE_URL`
3. Add **Redis** plugin → copy the `REDIS_URL`

### Step 2: Deploy backend

1. Connect your GitHub repo or push via Railway CLI
2. Set root directory: `backend`
3. Environment variables in Railway dashboard:

```
SECRET_KEY=<your-random-64-hex>
ANTHROPIC_API_KEY=sk-ant-...
DATABASE_URL=<auto-set by Railway Postgres plugin>
REDIS_URL=<from Railway Redis plugin>
QDRANT_URL=<external Qdrant Cloud or self-hosted>
TELEGRAM_BOT_TOKEN=<from @BotFather>
YOLO_DEVICE=cpu
DEMO_MODE=false
CORS_ORIGINS=["https://your-frontend.railway.app"]
```

### Step 3: Deploy frontend

1. Add another service, root directory: `frontend`
2. Build args:

```
NEXT_PUBLIC_API_URL=https://your-backend.railway.app/api/v1
NEXT_PUBLIC_WS_URL=wss://your-backend.railway.app/ws/events
```

### Step 4: Run migrations

Railway runs `alembic upgrade head` on every deploy automatically (see `Dockerfile` CMD).

---

## Connecting Hikvision Cameras

### Вариант 0: Hik-Connect Cloud (рекомендуется)

Самый простой способ — через облако. Используйте тот же логин что в приложении Hik-Connect на телефоне.

1. Добавьте в `.env`:
   ```
   HIKCONNECT_EMAIL=your@email.com
   HIKCONNECT_PASSWORD=your_password
   HIKCONNECT_REGION=eu
   ```
2. Или войдите через админ-панель → Настройка платформы → Hik-Connect (email + пароль)
3. В дашборде → Камеры → **+ Добавить** → **Hik-Connect Cloud** → все камеры из аккаунта подтянутся автоматически
4. Нажмите «Подключить» — система получит стрим из облака и начнёт AI-анализ

**Не нужен проброс портов, DDNS или доступ к локальной сети салона.**

### Вариант 1: Локальная сеть (Sentinel + камера в одной сети)

1. Откройте **Hik-Connect** → настройки камеры → IP-адрес (обычно `192.168.x.x`)
2. Или скачайте **SADP Tool** — автоматически найдёт все камеры
3. В Sentinel → Камеры → **+ Добавить камеру** → Hikvision
4. Введите IP, порт (`554`), логин (`admin`), пароль, канал
5. **Проверить подключение** → Подключить

### Вариант 2: Удалённый доступ (Sentinel на Railway, камеры в салоне)

Для салонов, где камеры за NAT (обычная ситуация), нужен один из способов:

**Способ A — Проброс порта на роутере:**
1. На роутере салона настройте проброс порта `554` (TCP) → IP камеры
2. Используйте внешний IP роутера или DDNS
3. В Sentinel введите внешний IP/DDNS вместо локального

**Способ B — Edge Agent (рекомендуется для 10+ салонов):**
1. Установите Edge Agent на мини-ПК (Raspberry Pi / любой Linux) в салоне
2. Edge Agent подключается к камерам по локальной сети
3. Обрабатывает видео локально (YOLO + трекинг)
4. Отправляет только события (JSON) на сервер Sentinel
5. Экономит трафик, работает при нестабильном интернете

```bash
# Запуск Edge Agent в салоне
docker run -d --name sentinel-edge \
  -e MASTER_URL=https://your-sentinel.railway.app \
  -e API_KEY=<salon_api_key> \
  -e CAMERA_URLS=rtsp://admin:pass@192.168.1.64:554/Streaming/Channels/101 \
  sentinel-edge:latest
```

### RTSP URL format

```
rtsp://<user>:<password>@<ip>:<port>/Streaming/Channels/<channel>01
```

---

## Zone Intelligence

Define zones on any camera (reception, entrance, service area) with rules:

- **Staff absence**: Alert if no staff member is in a "reception" zone for N minutes
- **Client unattended**: Alert if a client waits without staff nearby for N seconds
- **Zone enter/exit**: Track when people enter and leave specific areas

### API

```bash
# Create a zone
curl -X POST http://localhost:8000/api/v1/zones/camera/cam-entrance \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Ресепшен",
    "zone_type": "reception",
    "polygon": [[100,100],[400,100],[400,400],[100,400]],
    "staff_required": true,
    "max_absence_seconds": 300,
    "max_wait_seconds": 120
  }'
```

### Dashboard

Cameras → Zones tab → "+ Добавить зону" → configure polygon, type, and rules.

---

## Telegram Alerts

### Создание бота (один раз):

1. Откройте Telegram → найдите **@BotFather**
2. Отправьте `/newbot`
3. Имя: `Sentinel Alert` (или любое)
4. Username: `MyCompanyAlertBot` (уникальный, заканчивается на `Bot`)
5. Скопируйте токен вида `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`
6. Вставьте в `.env`:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
   ```
7. Перезапустите backend

### Подключение салона:

1. В админ-панели → карточка салона → раздел «Telegram»
2. Скопируйте команду `/start <api_key>`
3. Откройте вашего бота в Telegram
4. Отправьте скопированную команду
5. Готово — алерты (отсутствие персонала, подозрительная активность, нарушения зон) приходят в Telegram

### AI ключи

Для работы ИИ-нарративов и чат-ассистента:

**Anthropic (рекомендуется):**
1. Зарегистрируйтесь на [console.anthropic.com](https://console.anthropic.com)
2. Settings → API Keys → Create Key
3. Вставьте в `.env`: `ANTHROPIC_API_KEY=sk-ant-...`

**OpenAI (альтернатива):**
1. Зарегистрируйтесь на [platform.openai.com](https://platform.openai.com)
2. API Keys → Create new secret key
3. Вставьте в `.env`: `OPENAI_API_KEY=sk-...` и `LLM_PROVIDER=openai`

---

## Key Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/cameras/` | GET/POST | List/add cameras (DB-persisted) |
| `/api/v1/cameras/{id}` | DELETE | Remove camera |
| `/api/v1/cameras/test` | POST | Test RTSP connection |
| `/api/v1/cameras/{id}/heatmap` | GET | Visitor heatmap |
| `/api/v1/zones/` | GET | List all zones |
| `/api/v1/zones/camera/{id}` | GET/POST | Zones for camera |
| `/api/v1/zones/{id}` | PUT/DELETE | Update/remove zone |
| `/api/v1/persons/enroll` | POST | Register face |
| `/api/v1/persons/` | GET | List persons |
| `/api/v1/analytics/visits` | GET | Visit history |
| `/api/v1/analytics/alerts` | GET | Security alerts |
| `/api/v1/analytics/occupancy` | GET | Hourly occupancy |
| `/api/v1/analytics/summaries` | GET | LLM narratives |
| `/api/v1/chat/` | POST | AI Q&A |
| `/api/v1/admin/tenants` | GET/POST | Manage tenants |
| `/api/v1/admin/telegram` | PUT | Set Telegram chat |
| `/ws/events` | WS | Real-time event stream |
| `/api/v1/chat/ws` | WS | AI chat stream |
| `/health` | GET | Health check |

---

## Project Structure

```
sentinel-next/
├── backend/
│   ├── sentinel/
│   │   ├── api/routes/          # REST endpoints
│   │   │   ├── cameras.py       # Camera CRUD (DB-persisted)
│   │   │   ├── zones.py         # Zone CRUD
│   │   │   ├── analytics.py
│   │   │   ├── persons.py
│   │   │   ├── admin.py
│   │   │   └── chat.py
│   │   ├── api/websocket.py     # WS event gateway
│   │   ├── core/
│   │   │   ├── config.py        # Pydantic settings
│   │   │   ├── auth.py          # JWT + API key auth
│   │   │   └── events.py        # EventBus + SentinelEvent
│   │   ├── pipeline/
│   │   │   ├── camera.py        # RTSP/webcam reader
│   │   │   ├── processor.py     # Per-camera inference
│   │   │   └── manager.py       # Camera lifecycle
│   │   ├── services/
│   │   │   ├── ai/
│   │   │   │   ├── detection.py     # YOLOv11
│   │   │   │   ├── tracking.py      # ByteTrack
│   │   │   │   ├── face_reid.py     # InsightFace + Qdrant
│   │   │   │   └── zone_tracker.py  # Spatial intelligence
│   │   │   ├── llm/
│   │   │   │   ├── summarizer.py
│   │   │   │   └── chat_assistant.py
│   │   │   ├── notifications/
│   │   │   │   └── telegram.py      # Bot API alerts
│   │   │   └── analytics/
│   │   │       ├── heatmap.py
│   │   │       └── db_writer.py
│   │   └── db/
│   │       ├── models/
│   │       │   ├── person.py    # Person, Visit, Alert, Summary
│   │       │   ├── tenant.py    # Tenant, User, Agent
│   │       │   ├── camera.py    # Persisted cameras
│   │       │   └── zone.py      # Zone configuration
│   │       ├── queries/
│   │       └── migrations/
│   ├── alembic.ini
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/
│   └── src/
│       ├── app/                 # Next.js 15 App Router
│       ├── components/
│       │   ├── LoginGate.tsx
│       │   ├── admin/AdminPanel.tsx
│       │   └── dashboard/
│       │       ├── DashboardShell.tsx
│       │       ├── Sidebar.tsx
│       │       ├── OverviewPanel.tsx
│       │       ├── EventFeed.tsx
│       │       ├── CameraGrid.tsx
│       │       ├── ZonesPanel.tsx
│       │       ├── AnalyticsPanel.tsx
│       │       ├── PersonsPanel.tsx
│       │       └── ChatDrawer.tsx
│       └── lib/
│           ├── store.ts         # Zustand state
│           ├── ws.ts            # WebSocket client
│           └── api.ts           # REST client
├── edge-agent/                  # Local processing agent
├── infra/
│   ├── nginx/nginx.conf
│   └── scripts/
├── docker-compose.yml           # local + railway profiles
├── .env.example
└── README.md
```

---

## Multi-Tenancy

Each salon/location gets its own tenant with isolated data:

1. **Superadmin** creates tenants in Admin Panel
2. Each tenant gets a unique **API key**
3. Cameras, zones, persons, visits — all scoped by `tenant_id`
4. Superadmin sees everything; tenant admin sees only their data

---

## License

MIT — build something extraordinary.
