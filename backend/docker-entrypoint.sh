#!/bin/sh
set -e
cd /app
export PYTHONPATH=/app

if [ -z "${DATABASE_URL:-}" ] && [ -z "${POSTGRES_URL:-}" ] && [ -z "${POSTGRESQL_URL:-}" ]; then
  echo "❌ DATABASE_URL is not set."
  echo "   Railway → backend → Variables → Add Variable Reference → Postgres → DATABASE_URL"
  exit 1
fi

echo "🛡  Sentinel-Next — migrating DB…"
alembic upgrade head

echo "🛡  Sentinel-Next — starting API on :${PORT:-8000}"
exec uvicorn sentinel.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
