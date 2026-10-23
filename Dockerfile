# Sentinel-Next · Backend (Railway / Docker)
# Build context = repo root. No Root Directory / Start Command needed in Railway UI.

FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    ffmpeg libavcodec-dev libavformat-dev libswscale-dev \
    build-essential cmake git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Only backend package into /app → import sentinel works everywhere
COPY backend/pyproject.toml backend/alembic.ini ./
COPY backend/sentinel ./sentinel
RUN pip install --upgrade pip hatchling \
    && pip install .

# Don't pre-download YOLO in image build — slows Railway and burns RAM at boot
RUN mkdir -p /app/data/models /app/data/snapshots /app/logs

COPY backend/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD curl -sf http://localhost:${PORT:-8000}/health || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]
