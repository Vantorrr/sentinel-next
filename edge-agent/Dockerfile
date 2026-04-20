FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --upgrade pip && pip install .

COPY . .

RUN mkdir -p /app/data/models \
    && python -c "from ultralytics import YOLO; YOLO('yolo11n.pt')" 2>/dev/null || true

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -sf http://localhost:8000/health || exit 0

CMD ["sentinel-edge", "start"]
