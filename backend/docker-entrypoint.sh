#!/bin/sh
set -e
cd /app
export PYTHONPATH=/app

echo "🛡  Sentinel-Next — migrating DB…"
alembic upgrade head

echo "🛡  Sentinel-Next — starting API on :${PORT:-8000}"
exec uvicorn sentinel.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
