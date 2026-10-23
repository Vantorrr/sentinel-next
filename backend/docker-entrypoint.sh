#!/bin/sh
set -e
cd /app
export PYTHONPATH=/app

if [ -z "${DATABASE_URL:-}" ] && [ -z "${POSTGRES_URL:-}" ] && [ -z "${POSTGRESQL_URL:-}" ]; then
  echo "❌ DATABASE_URL is not set."
  echo "   Railway → backend → Variables → Add Variable Reference → Postgres → DATABASE_URL"
  exit 1
fi

if [ -z "${REDIS_URL:-}" ] && [ -z "${REDIS_PRIVATE_URL:-}" ]; then
  echo "❌ REDIS_URL is not set."
  echo "   Railway → + New → Database → Redis"
  echo "   backend Variables → Add Reference → Redis → REDIS_URL"
  exit 1
fi

# Prefer private URL when Railway injects both
if [ -n "${REDIS_PRIVATE_URL:-}" ] && [ -z "${REDIS_URL:-}" ]; then
  export REDIS_URL="$REDIS_PRIVATE_URL"
fi

echo "🛡  Sentinel-Next — migrating DB…"
alembic upgrade head

# Railway provides PORT (commonly 8080). Fall back only for local docker.
PORT="${PORT:-8080}"
echo "🛡  Sentinel-Next — starting API on :${PORT}"
exec uvicorn sentinel.main:app --host 0.0.0.0 --port "${PORT}" --workers 1
