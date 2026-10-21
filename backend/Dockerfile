FROM python:3.11-slim-bookworm AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System libs for OpenCV, PyAV, InsightFace
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    ffmpeg libavcodec-dev libavformat-dev libswscale-dev \
    build-essential cmake git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONPATH=/app

# Full source first — hatchling needs the `sentinel` package on disk to install it
COPY . .
RUN pip install --upgrade pip hatchling \
    && pip install .

# Pre-download YOLO nano weights
RUN mkdir -p /app/data/models /app/data/snapshots /app/logs \
    && python -c "from ultralytics import YOLO; YOLO('yolo11n.pt')" 2>/dev/null || true

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD curl -sf http://localhost:8000/health || exit 1

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
ENTRYPOINT ["/docker-entrypoint.sh"]
